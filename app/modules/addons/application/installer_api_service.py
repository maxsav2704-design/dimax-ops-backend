from __future__ import annotations

import uuid

from app.modules.addons.api.installer_schemas import (
    AddFactResponse,
    InstallerProjectAddonsResponse,
)
from app.modules.addons.application.use_cases import AddonsUseCases
from app.modules.addons.domain.enums import AddonFactSource
from app.shared.domain.errors import Forbidden


class AddonsInstallerApiService:
    @staticmethod
    def get_project_addons(
        uow,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID,
        installer_id: uuid.UUID,
    ) -> InstallerProjectAddonsResponse:
        my_doors = uow.doors.list_by_project_for_installer(
            company_id=company_id,
            project_id=project_id,
            installer_id=installer_id,
        )
        if not my_doors:
            raise Forbidden("Project is not assigned to this installer")

        plan_rows = uow.addon_plans.list_by_project(
            company_id=company_id, project_id=project_id
        )
        fact_rows = uow.addon_facts.list_by_project_for_installer(
            company_id=company_id,
            project_id=project_id,
            installer_id=installer_id,
        )

        return InstallerProjectAddonsResponse(
            project_id=project_id,
            plan=[
                {
                    "addon_type_id": str(p.addon_type_id),
                    "qty_planned": str(p.qty_planned),
                    "client_price": str(p.client_price),
                    "installer_price": str(p.installer_price),
                }
                for p in plan_rows
            ],
            facts=[
                {
                    "id": str(f.id),
                    "addon_type_id": str(f.addon_type_id),
                    "qty_done": str(f.qty_done),
                    "done_at": f.done_at.isoformat() if f.done_at else None,
                    "comment": f.comment,
                    "source": str(f.source),
                }
                for f in fact_rows
            ],
        )

    @staticmethod
    def add_fact(
        uow,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID,
        installer_id: uuid.UUID,
        addon_type_id: uuid.UUID,
        qty_done,
        comment: str | None,
        done_at,
        client_event_id: str | None,
    ) -> AddFactResponse:
        row = AddonsUseCases.installer_add_fact(
            uow,
            company_id=company_id,
            project_id=project_id,
            installer_id=installer_id,
            addon_type_id=addon_type_id,
            qty_done=qty_done,
            comment=comment,
            done_at=done_at,
            source=(
                AddonFactSource.OFFLINE if client_event_id else AddonFactSource.ONLINE
            ),
            client_event_id=client_event_id,
        )
        if row is None:
            return AddFactResponse(ok=True, applied=False, fact_id=None)
        return AddFactResponse(ok=True, applied=True, fact_id=row.id)
