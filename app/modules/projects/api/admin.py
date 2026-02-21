from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.v1.deps import CurrentUser, get_uow, require_admin
from app.modules.projects.api.schemas import (
    AssignInstallerBody,
    ImportDoorsResponse,
    ImportDoorsBody,
    OkResponse,
    ProjectCreateResponse,
    ProjectCreateBody,
    ProjectDetailsResponse,
    ProjectListResponse,
    ProjectUpdateBody,
)
from app.modules.projects.application.admin_service import ProjectAdminService


router = APIRouter(prefix="/admin/projects", tags=["Admin / Projects"])


@router.get("", response_model=ProjectListResponse)
def list_projects(
    q: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return ProjectAdminService.list_projects(
            uow,
            company_id=user.company_id,
            q=q,
            status=status,
            limit=limit,
            offset=offset,
        )


@router.post("", response_model=ProjectCreateResponse)
def create_project(
    body: ProjectCreateBody,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return ProjectAdminService.create_project(
            uow,
            company_id=user.company_id,
            name=body.name,
            address=body.address,
            developer_company=body.developer_company,
            contact_name=body.contact_name,
            contact_phone=body.contact_phone,
            contact_email=body.contact_email,
        )


@router.patch("/{project_id}", response_model=OkResponse)
def update_project(
    project_id: UUID,
    body: ProjectUpdateBody,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        ProjectAdminService.update_project(
            uow,
            company_id=user.company_id,
            project_id=project_id,
            payload=body.model_dump(exclude_unset=True),
        )
    return OkResponse()


@router.delete("/{project_id}", response_model=OkResponse)
def delete_project(
    project_id: UUID,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        ProjectAdminService.delete_project(
            uow,
            company_id=user.company_id,
            project_id=project_id,
        )
    return OkResponse()


@router.post("/{project_id}/doors/import", response_model=ImportDoorsResponse)
def import_doors(
    project_id: UUID,
    body: ImportDoorsBody,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return ProjectAdminService.import_doors(
            uow,
            company_id=user.company_id,
            project_id=project_id,
            rows=[r.model_dump() for r in body.rows],
        )


@router.get("/{project_id}", response_model=ProjectDetailsResponse)
def project_details(
    project_id: UUID,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return ProjectAdminService.project_details(
            uow,
            company_id=user.company_id,
            project_id=project_id,
        )


@router.post("/doors/{door_id}/assign-installer", response_model=OkResponse)
def assign_installer_to_door(
    door_id: UUID,
    body: AssignInstallerBody,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        ProjectAdminService.assign_installer_to_door(
            uow,
            company_id=user.company_id,
            door_id=door_id,
            installer_id=body.installer_id,
        )
    return OkResponse()
