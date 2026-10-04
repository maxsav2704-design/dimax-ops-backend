import hashlib
import json
from decimal import Decimal, InvalidOperation
from uuid import UUID

from app.modules.rates.application.timeline_service import FactoryPriceTimelineService
from app.modules.sync.application.price_review_dto import PriceConflictReview, PriceConflictSource
from app.shared.domain.errors import Conflict, NotFound, ValidationError


def _uuid(value):
    try:
        return UUID(value) if isinstance(value, str) else None
    except ValueError:
        return None


class PriceConflictReviewService:
    """Read-only diagnosis. A token detects stale review; it is not authorization."""

    @staticmethod
    def pending(uow, *, company_id: UUID, source: PriceConflictSource, item_id: UUID, for_update=False):
        if source == "sync_event":
            row = uow.sync_events.get_for_company(company_id=company_id, item_id=item_id, for_update=for_update)
            if row is None or row.apply_error != "CONFLICT_FACTORY_PRICE":
                raise NotFound("Price conflict not found")
            installer = uow.installers.get(company_id, row.installer_id)
            operation = row.event_type.value
        else:
            row = uow.sync_queue.get_for_company(company_id=company_id, item_id=item_id, for_update=for_update)
            if row is None or row.status not in ("CONFLICT", "BLOCKED") or row.conflict_code != "CONFLICT_FACTORY_PRICE":
                raise NotFound("Price conflict not found")
            installer = uow.installers.get_by_user_id(company_id=company_id, user_id=row.user_id)
            operation = row.operation_type
        return row, installer, operation

    @staticmethod
    def original(row, source):
        return {"source": source, "id": str(row.id), "company_id": str(row.company_id),
            "project_id": str(row.project_id), "payload": row.payload,
            "happened_at": row.client_happened_at.isoformat() if row.client_happened_at else None,
            "received_at": row.created_at.isoformat(),
            **({"installer_id": str(row.installer_id), "client_event_id": row.client_event_id,
                "operation_type": row.event_type.value} if source == "sync_event" else
               {"user_id": str(row.user_id), "entity_id": str(row.entity_id), "entity_type": row.entity_type,
                "base_version": row.base_version, "operation_type": row.operation_type})}

    @staticmethod
    def get(uow, *, company_id: UUID, source: PriceConflictSource, item_id: UUID) -> PriceConflictReview:
        row, installer, operation = PriceConflictReviewService.pending(
            uow, company_id=company_id, source=source, item_id=item_id)
        project = uow.projects.get(company_id=company_id, project_id=row.project_id) if row.project_id else None
        payload = row.payload or {}
        raw_seen = payload.get("price_list_id")
        seen = _uuid(raw_seen)
        seen_list = uow.price_lists.get(company_id, seen) if seen else None
        result = PriceConflictReview(source=source, id=row.id, project_id=row.project_id,
            project_name=project.name if project else None, installer_id=installer.id if installer else None,
            installer_name=installer.full_name if installer else None, performed_at=row.client_happened_at,
            received_at=row.created_at, seen_price_list_id=raw_seen[:80] if isinstance(raw_seen, str) else None,
            seen_version=seen_list.version if seen_list else None,
            seen_version_status=("MISSING" if "price_list_id" not in payload else "INVALID" if seen is None
                                 else "AVAILABLE" if seen_list else "UNAVAILABLE"),
            analysis_code="UNSUPPORTED_WORK")
        target_id, unit, work_context = None, None, {}
        version_known = True
        if operation == "DOOR_SET_STATUS" and payload.get("status") == "INSTALLED":
            result.work_kind, result.quantity = "DOOR", "1"
            door_id = _uuid(payload.get("door_id"))
            if source == "sync_queue":
                if row.entity_type != "door" or (door_id is not None and door_id != row.entity_id):
                    return result
                door_id = row.entity_id
            door = uow.doors.get(company_id=company_id, door_id=door_id) if door_id else None
            if door and door.project_id == row.project_id:
                result.work_label, target_id = door.unit_label, door.door_type_id
                work_context = {"door_type_id": str(door.door_type_id), "version": door.version,
                    "installer_id": str(door.installer_id), "status": door.status.value, "locked": door.is_locked}
                expected = row.base_version if source == "sync_queue" else payload.get("base_version", payload.get("previous_version"))
                version_known = type(expected) is int and expected == door.version
        elif operation == "ADDON_FACT_CREATE":
            if source == "sync_queue" and row.entity_type != "addon_fact":
                return result
            result.work_kind = "ADDON"
            raw_quantity = payload.get("qty_done")
            result.quantity = str(raw_quantity)[:80] if isinstance(raw_quantity, (str, int, float)) and not isinstance(raw_quantity, bool) else None
            addon_id = _uuid(payload.get("addon_type_id"))
            addon = uow.addon_types.get(company_id=company_id, addon_type_id=addon_id) if addon_id else None
            if addon:
                result.work_label, target_id, unit = addon.name, addon.id, addon.unit
                work_context = {"addon_type_id": str(addon.id), "unit": addon.unit,
                    "active": addon.is_active, "deleted": addon.deleted_at is not None}
        else:
            return result
        if target_id is None or project is None:
            result.analysis_code = "WORK_UNAVAILABLE"
            return result
        if result.performed_at is None:
            result.analysis_code = "MISSING_EXECUTION_TIME"
            return result
        # Compare independently of the device version. Resolution must revalidate under locks.
        try:
            quote = FactoryPriceTimelineService.quote(uow, company_id=company_id, kind=result.work_kind,
                target_id=target_id, performed_at=result.performed_at, legacy_queue="price_list_id" not in payload)
        except ValidationError:
            result.analysis_code = "INVALID_EXECUTION_TIME"
            return result
        except Conflict as exc:
            result.analysis_code = "MISSING_FACTORY_PRICE" if (exc.meta or {}).get("reason") == "MISSING_FACTORY_PRICE" else "INVALID_FACTORY_EVIDENCE"
            return result
        if quote is None:
            result.analysis_code = "NO_ACTIVE_FACTORY_PRICES"
            return result
        result.applicable_quote = quote
        if unit is not None and unit != quote.unit:
            result.analysis_code = "CATALOG_UNIT_CHANGED"
            return result
        try:
            result.preview_amount = quote.amount(Decimal(result.quantity or ""))
        except (InvalidOperation, ValidationError):
            result.analysis_code = "INVALID_QUANTITY"
            return result
        result.analysis_code = ("NO_VERSION" if result.seen_version_status == "MISSING" else
                                "INVALID_VERSION" if result.seen_version_status == "INVALID" else
                                "VERSION_MATCH" if seen == quote.price_list_id else "VERSION_MISMATCH")
        if (result.analysis_code == "VERSION_MISMATCH" and seen_list is not None and installer is not None
                and quote.selection == "AT_EXECUTION" and result.performed_at <= result.received_at and version_known):
            try:
                FactoryPriceTimelineService._receipt(uow, seen_list, at=result.performed_at)
            except Conflict:
                return result
            seen_item = next((item for item in uow.price_lists.items(company_id, seen_list.id)
                if item.kind == result.work_kind and (item.door_type_id or item.addon_type_id) == target_id), None)
            if seen_item is None or seen_item.unit != quote.unit:
                result.analysis_code = "ORIGINAL_PRICE_UNAVAILABLE"
                return result
            result.resolution_available = True
            result.review_token = hashlib.sha256(json.dumps({
                "original": PriceConflictReviewService.original(row, source), "work": work_context,
                "review": result.model_dump(mode="json", exclude={"review_token"}),
            }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return result
