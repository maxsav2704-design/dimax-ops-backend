from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from app.core.config import settings
from app.modules.audit.application.service import AuditService
from app.modules.rates.application.price_list_dto import (
    CreatePriceList,
    PriceListDetail,
    PriceListLine,
    PriceListPage,
    PriceListSummary,
)
from app.modules.rates.infrastructure.price_list_models import (
    FactoryPriceListItemORM,
    FactoryPriceListORM,
)
from app.shared.domain.errors import Conflict, NotFound, ValidationError


class FactoryPriceListsService:
    @staticmethod
    def _detail(uow, row: FactoryPriceListORM) -> PriceListDetail:
        return PriceListDetail(
            **PriceListSummary.model_validate(row).model_dump(),
            items=[
                PriceListLine(
                    kind=item.kind,
                    target_id=item.door_type_id or item.addon_type_id,
                    stage_code=item.stage_code,
                    name=item.name,
                    unit=item.unit,
                    installer_price=item.installer_price,
                )
                for item in uow.price_lists.items(row.company_id, row.id)
            ],
        )

    @classmethod
    def get(cls, uow, *, company_id: UUID, price_list_id: UUID) -> PriceListDetail:
        row = uow.price_lists.get(company_id, price_list_id)
        if row is None:
            raise NotFound("Price list not found")
        return cls._detail(uow, row)

    @staticmethod
    def list(uow, *, company_id: UUID, limit: int, offset: int) -> PriceListPage:
        rows, total = uow.price_lists.page(company_id, limit, offset)
        return PriceListPage(
            items=[PriceListSummary.model_validate(row) for row in rows],
            total=total,
            latest_version=uow.price_lists.latest_version(company_id),
        )

    @classmethod
    def create(
        cls, uow, *, company_id: UUID, actor_user_id: UUID, body: CreatePriceList,
    ) -> PriceListDetail:
        payload = body.model_dump(mode="json", exclude={"request_id", "items"})
        # DOOR / ADDON fingerprints stay byte-identical to earlier versions; only STAGE lines carry stage_code.
        payload["items"] = sorted(
            [
                {"kind": line.kind, "target_id": str(line.target_id),
                 "installer_price": format(line.installer_price, ".2f"),
                 **({"stage_code": line.stage_code} if line.kind == "STAGE" else {})}
                for line in body.items
            ],
            key=lambda item: (item["kind"], item["target_id"], item.get("stage_code", "")),
        )
        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

        # The tenant lock serializes version allocation and retry checks until UOW commit.
        if not uow.price_lists.lock_company(company_id):
            raise NotFound("Company not found")
        existing = uow.price_lists.by_request(company_id, body.request_id)
        if existing is not None:
            if existing.request_fingerprint != fingerprint:
                raise Conflict(
                    "Request ID was already used for a different price list", field="request_id",
                )
            return cls._detail(uow, existing)
        latest = uow.price_lists.latest_version(company_id)
        if latest != body.expected_latest_version:
            raise Conflict(
                "Price list changed; reload before creating a new version",
                field="expected_latest_version", meta={"latest_version": latest},
            )

        catalogs = {
            kind: uow.price_lists.catalog(
                company_id, "DOOR" if kind == "STAGE" else kind,
                {item.target_id for item in body.items if item.kind == kind},
            )
            for kind in ("DOOR", "ADDON", "STAGE")
        }
        stage_lines = [line for line in body.items if line.kind == "STAGE"]
        stages = {}
        if stage_lines:
            if not settings.WORK_STAGES_ENABLED:
                raise ValidationError("Work stages are not enabled on this server", field="items")
            stages = uow.price_lists.stage_catalog(company_id, {line.stage_code for line in stage_lines})
            unknown = sorted({line.stage_code for line in stage_lines} - set(stages))
            if unknown:
                raise ValidationError("Unknown or inactive stages: " + ", ".join(unknown), field="items")
        row = FactoryPriceListORM(
            id=uuid4(), company_id=company_id, version=latest + 1, request_id=body.request_id,
            request_fingerprint=fingerprint, reason=body.reason,
            agreement_reference=body.agreement_reference,
            created_by=actor_user_id, status="DRAFT", currency="ILS",
        )
        items: list[FactoryPriceListItemORM] = []
        for line in body.items:
            target = catalogs[line.kind].get(line.target_id)
            if target is None:
                raise ValidationError("Work type is unavailable in this company", field="items")
            name = target.name.strip()
            unit = "pcs" if line.kind in ("DOOR", "STAGE") else target.unit.strip()
            if line.kind == "STAGE":
                # One stage of one door: "<door type>: <stage>" at the stage's own rate, never a share of the door price.
                name = f"{name}: {stages[line.stage_code].name.strip()}"[:256]
            if not name or not unit:
                raise ValidationError(
                    "Work type name and unit must be filled in the catalog", field="items",
                )
            items.append(
                FactoryPriceListItemORM(
                    company_id=company_id, price_list_id=row.id, kind=line.kind,
                    door_type_id=line.target_id if line.kind in ("DOOR", "STAGE") else None,
                    addon_type_id=line.target_id if line.kind == "ADDON" else None,
                    stage_code=line.stage_code if line.kind == "STAGE" else None,
                    name=name, unit=unit,
                    installer_price=line.installer_price.quantize(Decimal("0.01")),
                )
            )
        uow.price_lists.add(row, items)
        AuditService.add(
            uow, company_id=company_id, actor_user_id=actor_user_id,
            entity_type="FACTORY_PRICE_LIST", entity_id=row.id, action="CREATE",
            reason=body.reason[:500],
            after={"version": row.version, "status": row.status, "item_count": len(items),
                   "reason": body.reason},
        )
        return cls._detail(uow, row)

    @classmethod
    def cancel(
        cls, uow, *, company_id: UUID, actor_user_id: UUID, price_list_id: UUID, reason: str,
    ) -> PriceListDetail:
        if not uow.price_lists.lock_company(company_id):
            raise NotFound("Company not found")
        row = uow.price_lists.get(company_id, price_list_id)
        if row is None:
            raise NotFound("Price list not found")
        if row.status == "CANCELLED":
            return cls._detail(uow, row)
        if row.status != "DRAFT":
            raise Conflict("Only a draft price list may be cancelled")
        row.status = "CANCELLED"
        row.cancelled_at = datetime.now(timezone.utc)
        row.cancelled_by = actor_user_id
        row.cancellation_reason = reason
        AuditService.add(
            uow, company_id=company_id, actor_user_id=actor_user_id,
            entity_type="FACTORY_PRICE_LIST", entity_id=row.id, action="CANCEL",
            reason=reason[:500], before={"status": "DRAFT"},
            after={"status": "CANCELLED", "reason": reason},
        )
        return cls._detail(uow, row)
