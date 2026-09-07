from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.v1.acl import get_current_installer_id
from app.api.v1.deps import CurrentUser, get_uow, require_installer
from app.modules.workspace.api.installer_schemas import InstallerWorkspaceResponse
from app.modules.workspace.application.installer_api_service import (
    InstallerWorkspaceApiService,
)


router = APIRouter(prefix="/installer/workspace", tags=["Installer / Workspace"])


@router.get("", response_model=InstallerWorkspaceResponse)
def get_workspace(
    user: CurrentUser = Depends(require_installer),
    installer_id: UUID = Depends(get_current_installer_id),
    uow=Depends(get_uow),
):
    with uow:
        return InstallerWorkspaceApiService.get_workspace(
            uow,
            company_id=user.company_id,
            installer_id=installer_id,
            actor_user_id=user.id,
        )
