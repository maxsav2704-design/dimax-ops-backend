from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.shared.domain.errors import Forbidden, NotFound


def _status_value(s) -> str:
    return s.value if hasattr(s, "value") else str(s)


class ProjectInstallerService:
    @staticmethod
    def list_my_projects(
        uow,
        *,
        company_id: uuid.UUID,
        installer_id: uuid.UUID,
    ) -> dict:
        project_ids = uow.doors.list_project_ids_for_installer(
            company_id=company_id, installer_id=installer_id
        )
        projects = uow.projects.list_by_ids(company_id=company_id, ids=project_ids)
        return {
            "items": [
                {
                    "id": p.id,
                    "name": p.name,
                    "address": p.address,
                    "status": _status_value(p.status),
                }
                for p in projects
            ]
        }

    @staticmethod
    def project_details(
        uow,
        *,
        company_id: uuid.UUID,
        installer_id: uuid.UUID,
        project_id: uuid.UUID,
    ) -> dict:
        project = uow.projects.get(company_id=company_id, project_id=project_id)
        if not project:
            raise NotFound("Project not found", details={"project_id": str(project_id)})

        my_doors = uow.doors.list_by_project_for_installer(
            company_id=company_id,
            project_id=project_id,
            installer_id=installer_id,
        )
        if not my_doors:
            raise Forbidden("Project is not assigned to this installer")

        issues = uow.issues.list_open_by_project_for_installer(
            company_id=company_id,
            project_id=project_id,
            installer_id=installer_id,
        )

        addon_types = uow.addon_types.list_active(company_id=company_id)
        addon_plan = uow.addon_plans.list_by_project(
            company_id=company_id, project_id=project_id
        )
        addon_facts = uow.addon_facts.list_by_project_for_installer(
            company_id=company_id,
            project_id=project_id,
            installer_id=installer_id,
        )

        return {
            "id": project.id,
            "name": project.name,
            "address": getattr(project, "address", None),
            "status": _status_value(project.status),
            "doors": [
                {
                    "id": d.id,
                    "unit_label": d.unit_label,
                    "door_type_id": d.door_type_id,
                    "our_price": d.our_price,
                    "status": _status_value(d.status),
                    "reason_id": d.reason_id,
                    "comment": d.comment,
                    "is_locked": d.is_locked,
                }
                for d in my_doors
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
            "addons": {
                "types": [
                    {"id": t.id, "name": t.name, "unit": t.unit} for t in addon_types
                ],
                "plan": [
                    {
                        "addon_type_id": x.addon_type_id,
                        "qty_planned": x.qty_planned,
                        "client_price": x.client_price,
                        "installer_price": x.installer_price,
                    }
                    for x in addon_plan
                ],
                "facts": [
                    {
                        "id": f.id,
                        "addon_type_id": f.addon_type_id,
                        "qty_done": f.qty_done,
                        "done_at": f.done_at,
                        "comment": f.comment,
                        "source": _status_value(f.source),
                    }
                    for f in addon_facts
                ],
            },
            "server_time": datetime.now(timezone.utc),
        }
