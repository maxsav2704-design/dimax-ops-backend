from __future__ import annotations

import uuid

from app.modules.projects.api.schemas import (
    ImportDoorsResponse,
    ProjectCreateResponse,
)
from app.modules.projects.application.use_cases import ProjectUseCases
from app.shared.domain.errors import NotFound


def _status_value(s) -> str:
    return s.value if hasattr(s, "value") else str(s)


class ProjectAdminService:
    @staticmethod
    def list_projects(
        uow,
        *,
        company_id: uuid.UUID,
        q: str | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> dict:
        items = uow.projects.list(
            company_id=company_id,
            q=q,
            status=status,
            limit=limit,
            offset=offset,
        )
        return {
            "items": [
                {
                    "id": p.id,
                    "name": p.name,
                    "address": p.address,
                    "status": _status_value(p.status),
                }
                for p in items
            ]
        }

    @staticmethod
    def create_project(
        uow,
        *,
        company_id: uuid.UUID,
        name: str,
        address: str,
        developer_company: str | None,
        contact_name: str | None,
        contact_phone: str | None,
        contact_email: str | None,
    ) -> ProjectCreateResponse:
        p = ProjectUseCases.create_project(
            uow,
            company_id=company_id,
            name=name,
            address=address,
            developer_company=developer_company,
            contact_name=contact_name,
            contact_phone=contact_phone,
            contact_email=contact_email,
        )
        return ProjectCreateResponse(id=p.id)

    @staticmethod
    def update_project(
        uow,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID,
        payload: dict,
    ) -> None:
        ProjectUseCases.update_project(
            uow,
            company_id=company_id,
            project_id=project_id,
            **payload,
        )

    @staticmethod
    def delete_project(
        uow,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID,
    ) -> None:
        ProjectUseCases.delete_project(
            uow,
            company_id=company_id,
            project_id=project_id,
        )

    @staticmethod
    def import_doors(
        uow,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID,
        rows: list[dict],
    ) -> ImportDoorsResponse:
        count = ProjectUseCases.import_doors(
            uow,
            company_id=company_id,
            project_id=project_id,
            rows=rows,
        )
        return ImportDoorsResponse(imported=count)

    @staticmethod
    def project_details(
        uow,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID,
    ) -> dict:
        project = uow.projects.get(company_id=company_id, project_id=project_id)
        if not project:
            raise NotFound(
                "Project not found", details={"project_id": str(project_id)}
            )

        doors = uow.doors.list_by_project(
            company_id=company_id, project_id=project_id
        )
        issues = uow.issues.list_open_by_project(
            company_id=company_id, project_id=project_id
        )

        return {
            "id": project.id,
            "name": project.name,
            "address": project.address,
            "status": _status_value(project.status),
            "developer_company": project.developer_company,
            "contact_name": project.contact_name,
            "contact_phone": project.contact_phone,
            "contact_email": project.contact_email,
            "doors": [
                {
                    "id": d.id,
                    "unit_label": d.unit_label,
                    "door_type_id": d.door_type_id,
                    "our_price": d.our_price,
                    "status": _status_value(d.status),
                    "installer_id": d.installer_id,
                    "reason_id": d.reason_id,
                    "comment": d.comment,
                    "is_locked": d.is_locked,
                }
                for d in doors
            ],
            "issues_open": [
                {
                    "id": i.id,
                    "door_id": i.door_id,
                    "status": _status_value(i.status),
                    "title": i.title,
                    "details": i.details,
                }
                for i in issues
            ],
        }

    @staticmethod
    def assign_installer_to_door(
        uow,
        *,
        company_id: uuid.UUID,
        door_id: uuid.UUID,
        installer_id: uuid.UUID,
    ) -> None:
        ProjectUseCases.assign_installer_to_door(
            uow,
            company_id=company_id,
            door_id=door_id,
            installer_id=installer_id,
        )
