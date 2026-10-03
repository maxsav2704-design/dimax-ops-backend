from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from app.modules.doors.application.pricing import resolve_completion_pricing
from app.modules.earnings.application.factory_pricing import FactoryEarningsPricing
from app.modules.earnings.infrastructure.ledger_queries import active_completed_work_filter
from app.modules.earnings.infrastructure.models import (
    ClientPriceSnapshotORM,
    CompletedWorkORM,
)
from app.shared.domain.errors import Conflict, ValidationError


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def resolve_installation_time(
    happened_at: datetime | None, *, received_at: datetime | None = None,
) -> datetime:
    received_at = received_at or utcnow()
    if happened_at is None:
        return received_at
    if happened_at.tzinfo is None:
        happened_at = happened_at.replace(tzinfo=timezone.utc)
    # Preserve offline work time, but never book future work from a fast device clock.
    return min(happened_at.astimezone(timezone.utc), received_at)


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
    legacy_price_queue: bool = False,
) -> CompletedWorkORM:
    if installer_id is None:
        raise ValidationError(
            "Installer must be assigned before completed work can be recorded",
            field="installer_id",
            meta={"door_id": str(door.id)},
        )

    existing = (
        uow.session.query(CompletedWorkORM)
        .filter(
            active_completed_work_filter(company_id),
            CompletedWorkORM.door_id == door.id,
            CompletedWorkORM.work_kind == "DOOR",
        )
        .order_by(CompletedWorkORM.completed_at.desc(), CompletedWorkORM.id.desc())
        .first()
    )
    if existing is not None:
        return existing

    completed_at = getattr(door, "installed_at", None) or utcnow()
    quote = FactoryEarningsPricing.quote(
        uow, company_id=company_id, kind="DOOR", target_id=door.door_type_id,
        performed_at=completed_at, legacy_queue=legacy_price_queue,
    )
    if quote is not None:
        if (getattr(door, "apply_surcharge_to_installer", False)
                and Decimal(str(getattr(door, "surcharge_pct", None) or "100.00")) != 100):
            raise Conflict("Installer surcharge is not part of the confirmed factory price", field="surcharge_pct")
        rate_snapshot = quote.rate
    else:
        rate_snapshot = resolve_installer_rate_snapshot(
            uow, company_id=company_id, installer_id=installer_id,
            door_type_id=door.door_type_id, at=completed_at,
            current_snapshot=getattr(door, "installer_rate_snapshot", None),
        )
    door.installer_rate_snapshot = rate_snapshot
    quantity = Decimal("1.00")
    pricing = resolve_completion_pricing(
        base_client_rate=Decimal(str(getattr(door, "our_price", None) or "0")),
        base_installer_rate=rate_snapshot,
        surcharge_pct=Decimal(str(getattr(door, "surcharge_pct", None) or "100.00")),
        apply_surcharge_to_installer=bool(
            getattr(door, "apply_surcharge_to_installer", False)
        ),
    )
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
    FactoryEarningsPricing.attach(uow, completed_work, quote)
    return completed_work


def reverse_completed_work_for_door(
    uow,
    *,
    company_id: uuid.UUID,
    door,
    reason: str,
) -> CompletedWorkORM | None:
    original = (
        uow.session.query(CompletedWorkORM)
        .filter(
            active_completed_work_filter(company_id),
            CompletedWorkORM.door_id == door.id,
            CompletedWorkORM.work_kind == "DOOR",
        )
        .order_by(CompletedWorkORM.completed_at.desc(), CompletedWorkORM.id.desc())
        .populate_existing()
        .with_for_update()
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
    FactoryEarningsPricing.copy_reversal(uow, original, reversal)
    return reversal
