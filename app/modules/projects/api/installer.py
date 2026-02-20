from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.v1.acl import get_current_installer_id
from app.api.v1.deps import CurrentUser, get_uow, require_installer
from app.modules.projects.api.installer_schemas import (
    AddonFactDTO,
    AddonPlanDTO,
    AddonTypeMiniDTO,
    InstallerDoorDTO,
    InstallerIssueDTO,
    InstallerProjectAddonsDTO,
    InstallerProjectDetailsResponse,
    InstallerProjectListItem,
    InstallerProjectListResponse,
)
from app.shared.domain.errors import Forbidden, NotFound


router = APIRouter(prefix="/installer/projects", tags=["Installer / Projects"])


def _status_value(s) -> str:
    return s.value if hasattr(s, "value") else str(s)


@router.get("", response_model=InstallerProjectListResponse)
def list_my_projects(
    user: CurrentUser = Depends(require_installer),
    installer_id: UUID = Depends(get_current_installer_id),
    uow=Depends(get_uow),
):
    with uow:
        project_ids = uow.doors.list_project_ids_for_installer(
            company_id=user.company_id, installer_id=installer_id
        )
        projects = uow.projects.list_by_ids(
            company_id=user.company_id, ids=project_ids
        )

        return InstallerProjectListResponse(
            items=[
                InstallerProjectListItem(
                    id=p.id,
                    name=p.name,
                    address=p.address,
                    status=_status_value(p.status),
                )
                for p in projects
            ]
        )


@router.get("/{project_id}", response_model=InstallerProjectDetailsResponse)
def project_details(
    project_id: UUID,
    user: CurrentUser = Depends(require_installer),
    installer_id: UUID = Depends(get_current_installer_id),
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

        my_doors = uow.doors.list_by_project_for_installer(
            company_id=user.company_id,
            project_id=project_id,
            installer_id=installer_id,
        )
        if not my_doors:
            raise Forbidden("Project is not assigned to this installer")

        issues = uow.issues.list_open_by_project_for_installer(
            company_id=user.company_id,
            project_id=project_id,
            installer_id=installer_id,
        )

        addon_types = uow.addon_types.list_active(company_id=user.company_id)
        addon_plan = uow.addon_plans.list_by_project(
            company_id=user.company_id, project_id=project_id
        )
        addon_facts = uow.addon_facts.list_by_project_for_installer(
            company_id=user.company_id,
            project_id=project_id,
            installer_id=installer_id,
        )

        addons_dto = InstallerProjectAddonsDTO(
            types=[
                AddonTypeMiniDTO(id=t.id, name=t.name, unit=t.unit)
                for t in addon_types
            ],
            plan=[
                AddonPlanDTO(
                    addon_type_id=x.addon_type_id,
                    qty_planned=x.qty_planned,
                    client_price=x.client_price,
                    installer_price=x.installer_price,
                )
                for x in addon_plan
            ],
            facts=[
                AddonFactDTO(
                    id=f.id,
                    addon_type_id=f.addon_type_id,
                    qty_done=f.qty_done,
                    done_at=f.done_at,
                    comment=f.comment,
                    source=_status_value(f.source),
                )
                for f in addon_facts
            ],
        )

        return InstallerProjectDetailsResponse(
            id=project.id,
            name=project.name,
            address=getattr(project, "address", None),
            status=_status_value(project.status),
            doors=[
                InstallerDoorDTO(
                    id=d.id,
                    unit_label=d.unit_label,
                    door_type_id=d.door_type_id,
                    our_price=d.our_price,
                    status=_status_value(d.status),
                    reason_id=d.reason_id,
                    comment=d.comment,
                    is_locked=d.is_locked,
                )
                for d in my_doors
            ],
            issues_open=[
                InstallerIssueDTO(
                    id=i.id,
                    door_id=i.door_id,
                    status=_status_value(i.status),
                    title=i.title,
                    details=i.details,
                )
                for i in issues
            ],
            addons=addons_dto,
            server_time=datetime.now(timezone.utc),
        )
