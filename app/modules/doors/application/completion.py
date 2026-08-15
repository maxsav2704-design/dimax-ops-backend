from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import not_, select

from app.modules.doors.application.pricing import resolve_completion_pricing
from app.modules.earnings.infrastructure.models import (
    ClientPriceSnapshotORM,
    CompletedWorkORM,
)
from app.shared.domain.errors import ValidationError


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def enum_value(value: object) -> str:
    return value.value if hasattr(value, "value") else str(value)


def resolve_installer_rate_snapshot(
    uow,
    *,
    company_id: uuid.UUID,
    installer_id: uuid.UUID | None,
    door_type_id: uuid.UUID,
    at: datetime | None = None,
    current_snapshot: Decimal | None = None,
) -> Decimal:
    if installer_id is None:
        raise ValidationError(
            "Installer must be assigned before a door can be installed",
            field="installer_id",
            meta={"door_type_id": str(door_type_id)},
        )
    snapshot = (
        Decimal(str(current_snapshot)) if current_snapshot is not None else None
    )
    if snapshot is not None and snapshot > 0:
        return snapshot

    rate = uow.installer_rates.get_by_keys(
        company_id=company_id,
        installer_id=installer_id,
        door_type_id=door_type_id,
        at=at,
    )
    price = Decimal(str(rate.price)) if rate is not None else None
    if price is None or price <= 0:
        raise ValidationError(
            "A positive installer rate is required before a door can be installed",
            field="installer_rate",
            meta={
                "installer_id": str(installer_id),
                "door_type_id": str(door_type_id),
            },
        )
    return price


def create_completed_work_for_door(
    uow,
    *,
    company_id: uuid.UUID,
    installer_id: uuid.UUID | None,
    door,
) -> CompletedWorkORM:
    if installer_id is None:
        raise ValidationError(
            "Installer must be assigned before completed work can be recorded",
            field="installer_id",
            meta={"door_id": str(door.id)},
        )

    raw_rate_snapshot = getattr(door, "installer_rate_snapshot", None)
    rate_snapshot = (
        Decimal(str(raw_rate_snapshot)) if raw_rate_snapshot is not None else None
    )
    if rate_snapshot is None or rate_snapshot <= 0:
        raise ValidationError(
            "A positive installer rate is required before completed work can be recorded",
            field="installer_rate",
            meta={
                "door_id": str(door.id),
                "installer_id": str(installer_id),
            },
        )

    reversed_ids = (
        select(CompletedWorkORM.correction_ref_id)
        .where(
            CompletedWorkORM.company_id == company_id,
            CompletedWorkORM.entry_type == "REVERSAL",
            CompletedWorkORM.correction_ref_id.is_not(None),
        )
    )
    existing = (
        uow.session.query(CompletedWorkORM)
        .filter(
            CompletedWorkORM.company_id == company_id,
            CompletedWorkORM.door_id == door.id,
            CompletedWorkORM.work_kind == "DOOR",
            CompletedWorkORM.entry_type == "ORIGINAL",
            not_(CompletedWorkORM.id.in_(reversed_ids)),
        )
        .order_by(CompletedWorkORM.completed_at.desc(), CompletedWorkORM.id.desc())
        .first()
    )
    if existing is not None:
        return existing

    quantity = Decimal("1.00")
    pricing = resolve_completion_pricing(
        base_client_rate=Decimal(str(getattr(door, "our_price", None) or "0")),
        base_installer_rate=rate_snapshot,
        surcharge_pct=Decimal(str(getattr(door, "surcharge_pct", None) or "100.00")),
        apply_surcharge_to_installer=bool(
            getattr(door, "apply_surcharge_to_installer", False)
        ),
    )
    completed_at = getattr(door, "installed_at", None) or utcnow()
    completed_work = CompletedWorkORM(
        company_id=company_id,
        project_id=door.project_id,
        door_id=door.id,
        installer_id=installer_id,
        completed_at=completed_at,
        quantity=quantity,
        rate_snapshot=pricing.final_installer_rate,
        amount_snapshot=pricing.final_installer_rate * quantity,
        work_kind="DOOR",
        entry_type="ORIGINAL",
        correction_ref_id=None,
        reason=None,
    )
    uow.session.add(completed_work)
    uow.session.flush()
    uow.session.add(
        ClientPriceSnapshotORM(
            company_id=company_id,
            completed_work_id=completed_work.id,
            base_client_rate=pricing.base_client_rate,
            final_client_rate=pricing.final_client_rate,
            final_installer_rate=pricing.final_installer_rate,
        )
    )
    return completed_work


def reverse_completed_work_for_door(
    uow,
    *,
    company_id: uuid.UUID,
    door,
    reason: str,
) -> CompletedWorkORM | None:
    reversed_ids = (
        select(CompletedWorkORM.correction_ref_id)
        .where(
            CompletedWorkORM.company_id == company_id,
            CompletedWorkORM.entry_type == "REVERSAL",
            CompletedWorkORM.correction_ref_id.is_not(None),
        )
    )
    original = (
        uow.session.query(CompletedWorkORM)
        .filter(
            CompletedWorkORM.company_id == company_id,
            CompletedWorkORM.door_id == door.id,
            CompletedWorkORM.entry_type == "ORIGINAL",
            not_(CompletedWorkORM.id.in_(reversed_ids)),
        )
        .order_by(CompletedWorkORM.completed_at.desc(), CompletedWorkORM.id.desc())
        .first()
    )
    if original is None:
        return None

    reversal = CompletedWorkORM(
        company_id=company_id,
        project_id=original.project_id,
        door_id=original.door_id,
        installer_id=original.installer_id,
        completed_at=utcnow(),
        quantity=Decimal(str(original.quantity)),
        rate_snapshot=-Decimal(str(original.rate_snapshot)),
        amount_snapshot=-Decimal(str(original.amount_snapshot)),
        work_kind=str(getattr(original, "work_kind", None) or "DOOR"),
        entry_type="REVERSAL",
        correction_ref_id=original.id,
        reason=reason,
    )
    uow.session.add(reversal)
    uow.session.flush()
    return reversal
