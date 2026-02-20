from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.v1.deps import CurrentUser, get_uow, require_admin
from app.modules.projects.api.schemas import (
    AssignInstallerBody,
    DoorDTO,
    ImportDoorsBody,
    IssueDTO,
    OkResponse,
    ProjectCreateBody,
    ProjectDetailsResponse,
    ProjectListItem,
    ProjectListResponse,
    ProjectUpdateBody,
)
from app.modules.projects.application.use_cases import ProjectUseCases
from app.shared.domain.errors import NotFound


router = APIRouter(prefix="/admin/projects", tags=["Admin / Projects"])


def _status_value(s) -> str:
    return s.value if hasattr(s, "value") else str(s)


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
        items = uow.projects.list(
            company_id=user.company_id,
            q=q,
            status=status,
            limit=limit,
            offset=offset,
        )
        return ProjectListResponse(
            items=[
                ProjectListItem(
                    id=p.id,
                    name=p.name,
                    address=p.address,
                    status=_status_value(p.status),
                )
                for p in items
            ]
        )


@router.post("", response_model=dict)
def create_project(
    body: ProjectCreateBody,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        p = ProjectUseCases.create_project(
            uow,
            company_id=user.company_id,
            name=body.name,
            address=body.address,
            developer_company=body.developer_company,
            contact_name=body.contact_name,
            contact_phone=body.contact_phone,
            contact_email=body.contact_email,
        )
        return {"id": str(p.id)}


@router.patch("/{project_id}", response_model=OkResponse)
def update_project(
    project_id: UUID,
    body: ProjectUpdateBody,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        payload = body.model_dump(exclude_unset=True)
        ProjectUseCases.update_project(
            uow,
            company_id=user.company_id,
            project_id=project_id,
            **payload,
        )
    return OkResponse()


@router.delete("/{project_id}", response_model=OkResponse)
def delete_project(
    project_id: UUID,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        ProjectUseCases.delete_project(
            uow,
            company_id=user.company_id,
            project_id=project_id,
        )
    return OkResponse()


@router.post("/{project_id}/doors/import", response_model=dict)
def import_doors(
    project_id: UUID,
    body: ImportDoorsBody,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        count = ProjectUseCases.import_doors(
            uow,
            company_id=user.company_id,
            project_id=project_id,
            rows=[r.model_dump() for r in body.rows],
        )
        return {"imported": count}


@router.get("/{project_id}", response_model=ProjectDetailsResponse)
def project_details(
    project_id: UUID,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        project = uow.projects.get(
            company_id=user.company_id, project_id=project_id
        )
        if not project:
            raise NotFound(
                "Project not found", details={"project_id": str(project_id)}
            )

        doors = uow.doors.list_by_project(
            company_id=user.company_id, project_id=project_id
        )
        issues = uow.issues.list_open_by_project(
            company_id=user.company_id, project_id=project_id
        )

        return ProjectDetailsResponse(
            id=project.id,
            name=project.name,
            address=project.address,
            status=_status_value(project.status),
            developer_company=project.developer_company,
            contact_name=project.contact_name,
            contact_phone=project.contact_phone,
            contact_email=project.contact_email,
            doors=[
                DoorDTO(
                    id=d.id,
                    unit_label=d.unit_label,
                    door_type_id=d.door_type_id,
                    our_price=d.our_price,
                    status=_status_value(d.status),
                    installer_id=d.installer_id,
                    reason_id=d.reason_id,
                    comment=d.comment,
                    is_locked=d.is_locked,
                )
                for d in doors
            ],
            issues_open=[
                IssueDTO(
                    id=i.id,
                    door_id=i.door_id,
                    status=_status_value(i.status),
                    title=i.title,
                    details=i.details,
                )
                for i in issues
            ],
        )


@router.post("/doors/{door_id}/assign-installer", response_model=OkResponse)
def assign_installer_to_door(
    door_id: UUID,
    body: AssignInstallerBody,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        ProjectUseCases.assign_installer_to_door(
            uow,
            company_id=user.company_id,
            door_id=door_id,
            installer_id=body.installer_id,
        )
    return OkResponse()
