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
from app.modules.addons.application.installer_api_service import (
    AddonsInstallerApiService,
)


router = APIRouter(prefix="/installer/addons", tags=["Installer / Add-ons"])


@router.get("/projects/{project_id}", response_model=InstallerProjectAddonsResponse)
def get_project_addons(
    project_id: UUID,
    user: CurrentUser = Depends(require_installer),
    installer_id: UUID = Depends(get_current_installer_id),
    uow=Depends(get_uow),
):
    with uow:
        return AddonsInstallerApiService.get_project_addons(
            uow,
            company_id=user.company_id,
            project_id=project_id,
            installer_id=installer_id,
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
        return AddonsInstallerApiService.add_fact(
            uow,
            company_id=user.company_id,
            project_id=project_id,
            installer_id=installer_id,
            addon_type_id=body.addon_type_id,
            qty_done=body.qty_done,
            comment=body.comment,
            done_at=body.done_at,
            client_event_id=body.client_event_id,
        )
