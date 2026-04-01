from __future__ import annotations

import uuid

from app.modules.doors.domain.enums import DoorStatus
from app.modules.projects.domain.enums import ProjectStatus


class ProjectStatusService:
    @staticmethod
    def recalc_and_set(
        *, uow, company_id: uuid.UUID, project_id: uuid.UUID
    ) -> None:
        project = uow.projects.get(company_id=company_id, project_id=project_id)
        if not project:
            return

        doors = uow.doors.list_by_project(
            company_id=company_id,
            project_id=project_id,
        )
        open_issues = uow.issues.list_open_by_project(
            company_id=company_id,
            project_id=project_id,
        )

        has_blocker = any(
            getattr(door, "status", None) == DoorStatus.ISSUE_OPEN for door in doors
        ) or bool(open_issues)
        has_pending = any(
            getattr(door, "status", None)
            not in {DoorStatus.INSTALLED, DoorStatus.CANCELLED, DoorStatus.LOCKED}
            for door in doors
        )

        project.status = (
            ProjectStatus.PROBLEM if (has_blocker or has_pending) else ProjectStatus.OK
        )
        project.health_status = (
            "BLOCKED" if has_blocker else "AT_RISK" if has_pending else "NORMAL"
        )
        uow.projects.save(project)
