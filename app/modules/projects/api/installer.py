from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.api.v1.acl import get_current_installer_id
from app.api.v1.pagination import paginate_items, pagination_params
from app.api.v1.deps import CurrentUser, get_uow, require_installer
from app.modules.projects.api.installer_schemas import (
    InstallerProjectDetailsResponse,
    InstallerProjectListResponse,
)
from app.modules.projects.application.installer_service import (
    ProjectInstallerService,
)


router = APIRouter(prefix="/installer/projects", tags=["Installer / Projects"])


@router.get("", response_model=InstallerProjectListResponse)
def list_my_projects(
    pagination: tuple[int, int] = Depends(pagination_params),
    user: CurrentUser = Depends(require_installer),
    installer_id: UUID = Depends(get_current_installer_id),
    uow=Depends(get_uow),
):
    page, per_page = pagination
    with uow:
        result = ProjectInstallerService.list_my_projects(
            uow,
            company_id=user.company_id,
            installer_id=installer_id,
        )
        return InstallerProjectListResponse(
            **paginate_items(result["items"], page=page, per_page=per_page)
        )


@router.get("/{project_id}", response_model=InstallerProjectDetailsResponse)
def project_details(
    project_id: UUID,
    request: Request,
    user: CurrentUser = Depends(require_installer),
    installer_id: UUID = Depends(get_current_installer_id),
    uow=Depends(get_uow),
):
    with uow:
        return ProjectInstallerService.project_details(
            uow,
            company_id=user.company_id,
            installer_id=installer_id,
            project_id=project_id,
            locale=request.headers.get("accept-language", "en"),
        )
