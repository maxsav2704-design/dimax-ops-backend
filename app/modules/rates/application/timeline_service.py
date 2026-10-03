from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.modules.audit.application.service import AuditService
from app.modules.rates.application.approval_service import approval_snapshot_matches
from app.modules.rates.application.reconciliation_service import FactoryPriceReconciliationService
from app.modules.rates.application.timeline_dto import ActivatePriceVersion, EffectivePriceVersion, FactoryPriceQuote
from app.modules.rates.infrastructure.timeline_models import FactoryPriceActivationORM
from app.shared.domain.errors import Conflict, Forbidden, NotFound, ValidationError
from app.shared.infrastructure.db.base import utcnow


class FactoryPriceTimelineService:
    """Internal transition engine; intentionally not exposed until mobile can cache price versions."""

    @staticmethod
    def activate(uow, *, company_id: UUID, actor_user_id: UUID, price_list_id: UUID,
                 body: ActivatePriceVersion) -> EffectivePriceVersion:
        if not uow.price_lists.lock_company(company_id):
            raise NotFound("Company not found")
        if not uow.price_lists.can_activate_prices(company_id, actor_user_id):
            raise Forbidden("Only an authorized company administrator may activate factory prices")
        payload = body.model_dump(mode="json", exclude={"request_id"})
        payload["price_list_id"] = str(price_list_id)
        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        existing = uow.price_lists.activation_by_request(company_id, body.request_id)
        if existing is not None:
            if existing.request_fingerprint != fingerprint:
                raise Conflict("Request ID was used for another price transition", field="request_id")
            return EffectivePriceVersion.model_validate(existing)
        previous = uow.price_lists.latest_activation(company_id)
        if (previous.price_list_id if previous else None) != body.expected_active_price_list_id:
            raise Conflict("Active price version changed; reload the transition", field="expected_active_price_list_id")
        price_list = uow.price_lists.get(company_id, price_list_id)
        if price_list is None:
            raise NotFound("Price list not found")
        if previous is not None and price_list.version <= uow.price_lists.get(company_id, previous.price_list_id).version:
            raise Conflict("An effective version cannot be reapplied or replaced with an older version")
        check = FactoryPriceReconciliationService.get(uow, company_id=company_id, price_list_id=price_list_id,
            limit=1, offset=0, issues_only=False, kind=None).application_check
        if check.blockers:
            raise Conflict("Factory price transition is blocked", field="price_list_id",
                           meta={"blockers": [item.model_dump() for item in check.blockers]})
        now = utcnow()
        receipt = FactoryPriceTimelineService._receipt(uow, price_list, at=now)
        if previous is not None and now <= previous.effective_from:
            raise Conflict("Server clock must advance before another price transition")
        row = FactoryPriceActivationORM(id=uuid4(), company_id=company_id, price_list_id=price_list_id,
            approval_id=receipt.id, request_id=body.request_id, request_fingerprint=fingerprint,
            snapshot_hash=receipt.snapshot_hash, effective_from=now, created_at=now, updated_at=now,
            created_by=actor_user_id, reason=body.reason)
        uow.price_lists.add_activation(row)
        AuditService.add(uow, company_id=company_id, actor_user_id=actor_user_id,
            entity_type="FACTORY_PRICE_LIST", entity_id=price_list_id, action="FACTORY_PRICE_VERSION_EFFECTIVE",
            reason=body.reason[:500], before={"price_list_id": str(previous.price_list_id) if previous else None},
            after={"activation_id": str(row.id), "version": price_list.version,
                   "approval_id": str(receipt.id), "snapshot_hash": receipt.snapshot_hash,
                   "effective_from": now.isoformat(), "reviewed_transition": True})
        return EffectivePriceVersion.model_validate(row)

    @staticmethod
    def _receipt(uow, price_list, *, at):
        receipt = uow.price_lists.confirmed_approval(price_list.company_id, price_list.id)
        if (price_list.status != "CONFIRMED" or receipt is None or receipt.revoked_at is not None
                or not receipt.created_at <= receipt.confirmed_at <= at
                or not approval_snapshot_matches(uow, price_list, receipt)):
            raise Conflict("Factory confirmation no longer matches this price version", field="price_list_id")
        return receipt

    @classmethod
    def _effective_receipt(cls, uow, activation):
        price_list = uow.price_lists.get(activation.company_id, activation.price_list_id)
        if price_list is None:
            raise Conflict("Effective price version is unavailable", field="price_list_id")
        receipt = cls._receipt(uow, price_list, at=activation.effective_from)
        if receipt.id != activation.approval_id or receipt.snapshot_hash != activation.snapshot_hash:
            raise Conflict("Effective price history no longer matches the factory decision", field="price_list_id")
        return price_list, receipt

    @classmethod
    def quote(cls, uow, *, company_id: UUID, kind: str, target_id: UUID, performed_at: datetime,
              seen_price_list_id: UUID | None = None, legacy_queue: bool = False) -> FactoryPriceQuote | None:
        if kind not in ("DOOR", "ADDON"):
            raise ValidationError("Unknown work kind", field="kind")
        if performed_at.tzinfo is None or performed_at.utcoffset() is None:
            raise ValidationError("Execution time must include its timezone", field="performed_at")
        performed_at = performed_at.astimezone(timezone.utc)
        if performed_at > utcnow():
            raise ValidationError("Execution time cannot be in the future", field="performed_at")
        activation = uow.price_lists.activation_at(company_id, performed_at)
        selection = "AT_EXECUTION"
        if activation is None:
            activation = uow.price_lists.first_activation(company_id)
            if activation is None:
                if seen_price_list_id is not None:
                    raise Conflict("No effective factory price version exists", field="price_list_id")
                return None
            if seen_price_list_id is not None:
                raise Conflict("This price version was not effective at execution time", field="price_list_id")
            # The caller must classify an old queue item; missing version alone must not backfill uploaded facts.
            if legacy_queue is not True:
                raise Conflict("Pre-transition work requires explicit legacy-queue resolution", field="price_list_id")
            cls._effective_receipt(uow, activation)
            price_list = uow.price_lists.first_confirmed_price_list(company_id)
            if price_list is None:
                raise Conflict("First factory confirmation is unavailable", field="price_list_id")
            receipt = cls._receipt(uow, price_list, at=activation.effective_from)
            selection = "FIRST_CONFIRMED_LEGACY"
        else:
            price_list, receipt = cls._effective_receipt(uow, activation)
            if seen_price_list_id is not None and seen_price_list_id != price_list.id:
                raise Conflict("Cached price differs from the effective price at execution time", field="price_list_id")
        item = next((row for row in uow.price_lists.items(company_id, price_list.id)
                     if row.kind == kind and (row.door_type_id or row.addon_type_id) == target_id), None)
        if item is None:
            raise Conflict("The applicable factory list has no price for this work", field="price_list_id",
                           meta={"reason": "MISSING_FACTORY_PRICE"})
        return FactoryPriceQuote(price_list_id=price_list.id, price_list_item_id=item.id, version=price_list.version,
            approval_id=receipt.id, activation_id=activation.id, kind=kind, target_id=target_id,
            unit=item.unit, rate=item.installer_price, currency=price_list.currency, performed_at=performed_at,
            effective_from=activation.effective_from, selection=selection, snapshot_hash=receipt.snapshot_hash)
