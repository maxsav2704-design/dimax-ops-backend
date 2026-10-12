from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from sqlalchemy.exc import IntegrityError

from app.modules.addons.domain.enums import AddonFactSource
from app.modules.addons.application.pricing import AddonPlanPricing
from app.modules.doors.application.completion import enum_value
from app.modules.addons.infrastructure.models import (
    AddonTypeORM,
    ProjectAddonFactORM,
    ProjectUrgencySurchargeORM,
)
from app.modules.earnings.infrastructure.models import CompletedWorkORM
from app.modules.earnings.application.factory_pricing import FactoryEarningsPricing
from app.modules.earnings.application.execution_authority import ExecutionAuthority
from app.modules.sync.domain.enums import SyncChangeType
from app.shared.domain.errors import Conflict, Forbidden, NotFound, ValidationError


_CENT = Decimal("0.01")
_MAX_DECIMAL = Decimal("9999999999.99")


def validate_fact_quantity(value) -> Decimal:
    try:
        quantity = Decimal(str(value))
        if not quantity.is_finite() or not 0 < quantity <= _MAX_DECIMAL:
            raise ValueError
        normalized = quantity.quantize(_CENT)
        if quantity != normalized:
            raise ValueError
        return normalized
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError(
            "qty_done must be positive with at most 10 integer and 2 decimal digits",
            field="qty_done",
        ) from None


def ensure_same_fact(existing, *, project_id, installer_id, addon_type_id, qty_done, comment, done_at) -> None:
    if done_at is not None and done_at.tzinfo is None:
        done_at = done_at.replace(tzinfo=timezone.utc)
    if (
        existing.project_id != project_id or existing.installer_id != installer_id
        or existing.addon_type_id != addon_type_id or existing.qty_done != qty_done
        or (existing.comment or None) != (comment or None)
        or (done_at is not None and existing.done_at != done_at)
    ):
        raise Conflict("client_event_id was already used for different additional work", field="client_event_id")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def create_completed_work_for_addon_fact(
    uow,
    *,
    company_id: uuid.UUID,
    fact: ProjectAddonFactORM,
    plan,
    legacy_price_queue: bool = False,
    seen_price_list_id: uuid.UUID | None = None,
) -> CompletedWorkORM | None:
    if Decimal(str(fact.qty_done or 0)) <= 0:
        return None

    existing = (
        uow.session.query(CompletedWorkORM.id)
        .filter(
            CompletedWorkORM.company_id == company_id,
            CompletedWorkORM.addon_fact_id == fact.id,
        )
        .first()
    )
    if existing is not None:
        return None

    quantity = Decimal(str(fact.qty_done))
    completed_at = fact.done_at or utcnow()
    quote = FactoryEarningsPricing.quote(
        uow, company_id=company_id, kind="ADDON", target_id=fact.addon_type_id,
        performed_at=completed_at, legacy_queue=legacy_price_queue, seen_price_list_id=seen_price_list_id,
    )
    if quote is None and (plan is None or Decimal(str(plan.installer_price or 0)) <= 0):
        return None
    rate = quote.rate if quote is not None else Decimal(str(plan.installer_price))
    amount = quote.amount(quantity) if quote is not None else (quantity * rate).quantize(_CENT, rounding=ROUND_HALF_UP)
    if not 0 < amount <= _MAX_DECIMAL:
        raise ValidationError(
            "Quantity multiplied by the installer rate must round to 0.01 through 9999999999.99",
            field="qty_done",
        )
    completed = CompletedWorkORM(
        company_id=company_id,
        project_id=fact.project_id,
        door_id=None,
        addon_fact_id=fact.id,
        installer_id=fact.installer_id,
        completed_at=completed_at,
        quantity=quantity,
        rate_snapshot=rate,
        amount_snapshot=amount,
        work_kind="ADDON",
        entry_type="ORIGINAL",
        correction_ref_id=None,
        reason=f"Additional work {fact.addon_type_id}",
    )
    uow.session.add(completed)
    FactoryEarningsPricing.attach(uow, completed, quote)
    return completed


def reconcile_addon_fact_earnings(
    uow,
    *,
    company_id: uuid.UUID,
    project_id: uuid.UUID,
    addon_type_id: uuid.UUID,
    plan,
) -> None:
    if FactoryEarningsPricing.is_active(uow, company_id):
        return
    facts = uow.addon_facts.list_by_project_type(
        company_id=company_id,
        project_id=project_id,
        addon_type_id=addon_type_id,
    )
    for fact in facts:
        create_completed_work_for_addon_fact(
            uow,
            company_id=company_id,
            fact=fact,
            plan=plan,
        )


class AddonsUseCases:
    @staticmethod
    def admin_create_addon_type(
        uow,
        *,
        company_id: uuid.UUID,
        name: str,
        unit: str,
        default_client_price: Decimal,
        default_installer_price: Decimal,
    ) -> AddonTypeORM:
        FactoryEarningsPricing.lock_company(uow, company_id)
        if FactoryEarningsPricing.is_active(uow, company_id) and default_installer_price != 0:
            AddonPlanPricing.reject_override()
        row = AddonTypeORM(
            company_id=company_id,
            name=name.strip(),
            unit=unit.strip() or "pcs",
            default_client_price=default_client_price,
            default_installer_price=default_installer_price,
            is_active=True,
        )
        uow.addon_types.create(row)
        return row

    @staticmethod
    def admin_set_project_plan(
        uow,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID,
        addon_type_id: uuid.UUID,
        qty_planned: Decimal,
        client_price: Decimal,
        installer_price: Decimal | None,
        notes: str | None = None,
    ):
        FactoryEarningsPricing.lock_company(uow, company_id)
        p = uow.projects.get(company_id=company_id, project_id=project_id, for_update=True)
        if not p:
            raise NotFound("Project not found")
        at = uow.addon_types.get(
            company_id=company_id, addon_type_id=addon_type_id
        )
        if not at:
            raise NotFound("Addon type not found")

        installer_price = AddonPlanPricing.plan_write_price(uow, company_id=company_id,
            project_id=project_id, addon_type_id=addon_type_id, submitted=installer_price)
        row = uow.addon_plans.upsert(
            company_id=company_id,
            project_id=project_id,
            addon_type_id=addon_type_id,
            qty_planned=qty_planned,
            client_price=client_price,
            installer_price=installer_price,
            notes=clean_optional_text(notes),
        )
        uow.session.flush()
        reconcile_addon_fact_earnings(
            uow,
            company_id=company_id,
            project_id=project_id,
            addon_type_id=addon_type_id,
            plan=row,
        )
        uow.sync_change_log.add_change(
            company_id=company_id,
            change_type=SyncChangeType.PROJECT_ADDON_PLAN,
            entity_id=project_id,
            project_id=project_id,
            installer_id=None,
            payload={
                "kind": "addon_plan_upsert",
                "project_id": str(project_id),
                "plan_items": [
                    {
                        "addon_type_id": str(addon_type_id),
                        "qty_planned": str(qty_planned),
                    }
                ],
            },
        )
        return row

    @staticmethod
    def admin_set_project_plan_batch(
        uow,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID,
        items: list[dict],
    ) -> None:
        FactoryEarningsPricing.lock_company(uow, company_id)
        p = uow.projects.get(company_id=company_id, project_id=project_id, for_update=True)
        if not p:
            raise NotFound("Project not found")

        for it in items:
            if not uow.addon_types.get(company_id=company_id, addon_type_id=it["addon_type_id"]):
                raise NotFound("Addon type not found")
            installer_price = AddonPlanPricing.plan_write_price(uow, company_id=company_id,
                project_id=project_id, addon_type_id=it["addon_type_id"], submitted=it.get("installer_price"))
            row = uow.addon_plans.upsert(
                company_id=company_id,
                project_id=project_id,
                addon_type_id=it["addon_type_id"],
                qty_planned=it["qty_planned"],
                client_price=it["client_price"],
                installer_price=installer_price,
                notes=clean_optional_text(it.get("notes")),
            )
            uow.session.flush()
            reconcile_addon_fact_earnings(
                uow,
                company_id=company_id,
                project_id=project_id,
                addon_type_id=it["addon_type_id"],
                plan=row,
            )

        # после применения всех items — кладем одно "проектное" изменение в change log
        uow.sync_change_log.add_change(
            company_id=company_id,
            change_type=SyncChangeType.PROJECT_ADDON_PLAN,
            entity_id=project_id,
            project_id=project_id,
            installer_id=None,
            payload={
                "kind": "addon_plan_upsert",
                "project_id": str(project_id),
                "plan_items": [
                    {
                        "addon_type_id": str(it["addon_type_id"]),
                        "qty_planned": str(it["qty_planned"]),
                    }
                    for it in items
                ],
            },
        )

    @staticmethod
    def admin_delete_project_plan_item(
        uow,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID,
        addon_type_id: uuid.UUID,
    ) -> None:
        FactoryEarningsPricing.lock_company(uow, company_id)
        p = uow.projects.get(company_id=company_id, project_id=project_id, for_update=True)
        if not p:
            raise NotFound("Project not found")

        uow.addon_plans.delete(
            company_id=company_id,
            project_id=project_id,
            addon_type_id=addon_type_id,
        )

        uow.sync_change_log.add_change(
            company_id=company_id,
            change_type=SyncChangeType.PROJECT_ADDON_PLAN,
            entity_id=project_id,
            project_id=project_id,
            installer_id=None,
            payload={
                "kind": "addon_plan_delete",
                "project_id": str(project_id),
                "deleted_addon_type_id": str(addon_type_id),
            },
        )

    @staticmethod
    def admin_create_urgency_surcharge(
        uow,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID,
        scope: str,
        order_number: str | None,
        reason: str,
        client_amount: Decimal,
        installer_amount: Decimal,
        effective_date: date | None,
        notes: str | None,
    ) -> ProjectUrgencySurchargeORM:
        FactoryEarningsPricing.lock_company(uow, company_id)
        if FactoryEarningsPricing.is_active(uow, company_id):
            raise Conflict("Use additional work with a confirmed factory price instead of a manual surcharge",
                field="installer_amount", meta={"reason": "FACTORY_URGENCY_REQUIRES_ADDON"})
        p = uow.projects.get(company_id=company_id, project_id=project_id)
        if not p:
            raise NotFound("Project not found")

        normalized_scope = scope.strip().upper()
        if normalized_scope not in {"PROJECT", "ORDER_NUMBER"}:
            raise ValidationError("scope must be PROJECT or ORDER_NUMBER")

        normalized_order = order_number.strip() if order_number else None
        if normalized_scope == "ORDER_NUMBER" and not normalized_order:
            raise ValidationError("order_number is required for order scope")
        if normalized_scope == "PROJECT":
            normalized_order = None

        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ValidationError("reason is required")
        if client_amount <= 0 or installer_amount <= 0:
            raise ValidationError("surcharge amounts must be > 0")

        row = ProjectUrgencySurchargeORM(
            company_id=company_id,
            project_id=project_id,
            scope=normalized_scope,
            order_number=normalized_order,
            reason=normalized_reason,
            client_amount=client_amount,
            installer_amount=installer_amount,
            effective_date=effective_date,
            notes=clean_optional_text(notes),
        )
        uow.project_urgency_surcharges.create(row)
        return row

    @staticmethod
    def installer_add_fact(
        uow,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID,
        installer_id: uuid.UUID,
        addon_type_id: uuid.UUID,
        qty_done: Decimal,
        comment: str | None,
        done_at: datetime | None,
        source: AddonFactSource,
        client_event_id: str | None,
        legacy_price_queue: bool = False,
        seen_price_list_id: uuid.UUID | None = None,
        execution_received_at: datetime | None = None,
        execution_has_timezone: bool | None = None,
        reviewed_execution: bool = False,
    ) -> ProjectAddonFactORM | None:
        qty_done = validate_fact_quantity(qty_done)
        if client_event_id is not None and (not client_event_id.strip() or len(client_event_id) > 80):
            raise ValidationError("client_event_id must contain 1 to 80 characters", field="client_event_id")

        # Serialize plan pricing/reconciliation with fact creation, even when no plan exists yet.
        FactoryEarningsPricing.lock_company(uow, company_id)
        project = uow.projects.get(company_id=company_id, project_id=project_id, for_update=True)
        if project is None:
            raise Forbidden("Project is not assigned to this installer")

        my_doors = uow.doors.list_by_project_for_installer(
            company_id=company_id,
            project_id=project_id,
            installer_id=installer_id,
        )
        if not my_doors:
            raise Forbidden("Project is not assigned to this installer")

        at = uow.addon_types.get(
            company_id=company_id, addon_type_id=addon_type_id
        )
        if not at or at.deleted_at is not None or not at.is_active:
            raise NotFound("Addon type not found or inactive")

        replay_fields = dict(
            project_id=project_id, installer_id=installer_id, addon_type_id=addon_type_id,
            qty_done=qty_done, comment=comment, done_at=done_at,
        )
        if client_event_id:
            existing = uow.addon_facts.get_by_client_event(company_id=company_id, client_event_id=client_event_id)
            if existing is not None:
                ensure_same_fact(existing, **replay_fields)
                return None

        if done_at is not None and not reviewed_execution and FactoryEarningsPricing.is_active(uow, company_id):
            # Direct uploads must not bypass the offline queue's historical-price checks.
            legacy_price_queue = ExecutionAuthority.inspect(uow, company_id=company_id, project_id=project_id,
                installer_id=installer_id, performed_at=done_at, received_at=execution_received_at or utcnow(),
                has_timezone=(execution_has_timezone if execution_received_at is not None
                              else done_at.utcoffset() is not None), lock_assignments=True).require_automatic()

        row = ProjectAddonFactORM(
            company_id=company_id,
            project_id=project_id,
            installer_id=installer_id,
            addon_type_id=addon_type_id,
            qty_done=qty_done,
            done_at=done_at or utcnow(),
            comment=comment,
            source=source,
            client_event_id=client_event_id,
        )
        try:
            with uow.session.begin_nested():
                uow.addon_facts.create(row)
                uow.session.flush()
        except IntegrityError:
            existing = uow.addon_facts.get_by_client_event(
                company_id=company_id, client_event_id=client_event_id,
            ) if client_event_id else None
            if existing is None:
                raise
            ensure_same_fact(existing, **replay_fields)
            return None
        plan = uow.addon_plans.get_by_project_type(
            company_id=company_id,
            project_id=project_id,
            addon_type_id=addon_type_id,
        )
        create_completed_work_for_addon_fact(
            uow, company_id=company_id, fact=row, plan=plan,
            legacy_price_queue=legacy_price_queue,
            seen_price_list_id=seen_price_list_id,
        )

        uow.sync_change_log.add_change(
            company_id=company_id,
            change_type=SyncChangeType.ADDON_FACT,
            entity_id=row.id,
            project_id=row.project_id,
            installer_id=row.installer_id,
            payload={
                "id": str(row.id),
                "project_id": str(row.project_id),
                "addon_type_id": str(row.addon_type_id),
                "installer_id": str(row.installer_id),
                "qty_done": str(row.qty_done),
                "done_at": row.done_at.isoformat(),
                "comment": row.comment,
                "source": enum_value(row.source),
                "updated_at": (
                    row.updated_at.isoformat() if row.updated_at else None
                ),
            },
        )
        return row
