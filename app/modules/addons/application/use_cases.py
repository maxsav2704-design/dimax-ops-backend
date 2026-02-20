from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from app.modules.addons.domain.enums import AddonFactSource
from app.modules.addons.infrastructure.models import AddonTypeORM, ProjectAddonFactORM
from app.modules.sync.domain.enums import SyncChangeType
from app.shared.domain.errors import Forbidden, NotFound, ValidationError


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


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
    ):
        p = uow.projects.get(company_id=company_id, project_id=project_id)
        if not p:
            raise NotFound("Project not found")
        at = uow.addon_types.get(
            company_id=company_id, addon_type_id=addon_type_id
        )
        if not at:
            raise NotFound("Addon type not found")

        return uow.addon_plans.upsert(
            company_id=company_id,
            project_id=project_id,
            addon_type_id=addon_type_id,
            qty_planned=qty_planned,
            client_price=client_price,
            installer_price=installer_price,
        )

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
            uow.addon_plans.upsert(
                company_id=company_id,
                project_id=project_id,
                addon_type_id=it["addon_type_id"],
                qty_planned=it["qty_planned"],
                client_price=it["client_price"],
                installer_price=it["installer_price"],
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
                        "client_price": str(it["client_price"]),
                        "installer_price": str(it["installer_price"]),
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
                "source": str(row.source),
                "updated_at": (
                    row.updated_at.isoformat() if row.updated_at else None
                ),
            },
        )
        return row
