from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from app.modules.addons.domain.enums import AddonFactSource
from app.modules.doors.application.completion import enum_value
from app.modules.addons.infrastructure.models import (
    AddonTypeORM,
    ProjectAddonFactORM,
    ProjectUrgencySurchargeORM,
)
from app.modules.earnings.infrastructure.models import CompletedWorkORM
from app.modules.sync.domain.enums import SyncChangeType
from app.shared.domain.errors import Forbidden, NotFound, ValidationError


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
) -> CompletedWorkORM | None:
    if Decimal(str(fact.qty_done or 0)) <= 0:
        return None
    if Decimal(str(plan.installer_price or 0)) <= 0:
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
    rate = Decimal(str(plan.installer_price))
    completed = CompletedWorkORM(
        company_id=company_id,
        project_id=fact.project_id,
        door_id=None,
        addon_fact_id=fact.id,
        installer_id=fact.installer_id,
        completed_at=fact.done_at or utcnow(),
        quantity=quantity,
        rate_snapshot=rate,
        amount_snapshot=quantity * rate,
        work_kind="ADDON",
        entry_type="ORIGINAL",
        correction_ref_id=None,
        reason=f"Additional work {fact.addon_type_id}",
    )
    uow.session.add(completed)
    return completed


def reconcile_addon_fact_earnings(
    uow,
    *,
    company_id: uuid.UUID,
    project_id: uuid.UUID,
    addon_type_id: uuid.UUID,
    plan,
) -> None:
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
        installer_price: Decimal,
        notes: str | None = None,
    ):
        p = uow.projects.get(company_id=company_id, project_id=project_id)
        if not p:
            raise NotFound("Project not found")
        at = uow.addon_types.get(
            company_id=company_id, addon_type_id=addon_type_id
        )
        if not at:
            raise NotFound("Addon type not found")

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
        p = uow.projects.get(company_id=company_id, project_id=project_id)
        if not p:
            raise NotFound("Project not found")

        for it in items:
            row = uow.addon_plans.upsert(
                company_id=company_id,
                project_id=project_id,
                addon_type_id=it["addon_type_id"],
                qty_planned=it["qty_planned"],
                client_price=it["client_price"],
                installer_price=it["installer_price"],
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
        p = uow.projects.get(company_id=company_id, project_id=project_id)
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
    ) -> ProjectAddonFactORM | None:
        if qty_done <= 0:
            raise ValidationError("qty_done must be > 0")

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

        if client_event_id and uow.addon_facts.exists_client_event(
            company_id=company_id, client_event_id=client_event_id
        ):
            return None

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
        uow.addon_facts.create(row)
        uow.session.flush()
        plan = uow.addon_plans.get_by_project_type(
            company_id=company_id,
            project_id=project_id,
            addon_type_id=addon_type_id,
        )
        if plan is not None:
            create_completed_work_for_addon_fact(
                uow,
                company_id=company_id,
                fact=row,
                plan=plan,
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
