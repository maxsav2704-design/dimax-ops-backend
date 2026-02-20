from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.v1.acl import get_current_installer_id
from app.api.v1.deps import CurrentUser, get_uow, require_installer
from app.modules.addons.api.installer_schemas import (
    AddFactBody,
    AddFactResponse,
    InstallerProjectAddonsResponse,
)
from app.modules.addons.application.use_cases import AddonsUseCases
from app.modules.addons.domain.enums import AddonFactSource
from app.shared.domain.errors import Forbidden


router = APIRouter(prefix="/installer/addons", tags=["Installer / Add-ons"])


@router.get("/projects/{project_id}", response_model=InstallerProjectAddonsResponse)
def get_project_addons(
    project_id: UUID,
    user: CurrentUser = Depends(require_installer),
    installer_id: UUID = Depends(get_current_installer_id),
    uow=Depends(get_uow),
):
    with uow:
        my_doors = uow.doors.list_by_project_for_installer(
            company_id=user.company_id,
            project_id=project_id,
            installer_id=installer_id,
        )
        if not my_doors:
            raise Forbidden("Project is not assigned to this installer")

        plan_rows = uow.addon_plans.list_by_project(
            company_id=user.company_id, project_id=project_id
        )
        fact_rows = uow.addon_facts.list_by_project_for_installer(
            company_id=user.company_id,
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


@router.post("/projects/{project_id}/facts", response_model=AddFactResponse)
def add_fact(
    project_id: UUID,
    body: AddFactBody,
    user: CurrentUser = Depends(require_installer),
    installer_id: UUID = Depends(get_current_installer_id),
    uow=Depends(get_uow),
):
    with uow:
        row = AddonsUseCases.installer_add_fact(
            uow,
            company_id=user.company_id,
            project_id=project_id,
            installer_id=installer_id,
            addon_type_id=body.addon_type_id,
            qty_done=body.qty_done,
            comment=body.comment,
            done_at=body.done_at,
            source=(
                AddonFactSource.OFFLINE
                if body.client_event_id
                else AddonFactSource.ONLINE
            ),
            client_event_id=body.client_event_id,
        )

        if row is None:
            return AddFactResponse(ok=True, applied=False, fact_id=None)

        return AddFactResponse(ok=True, applied=True, fact_id=row.id)
