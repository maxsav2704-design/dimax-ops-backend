from __future__ import annotations

import uuid
from datetime import date

from app.modules.doors.application.completion import enum_value
from app.modules.doors.domain.enums import DoorStatus
from app.modules.projects.application.sync_payload import build_project_sync_payload
from app.modules.projects.domain.enums import (
    ProjectHealthStatus,
    ProjectLifecycleStatus,
    ProjectStatus,
)
from app.modules.sync.domain.enums import SyncChangeType


class ProjectStatusService:
    @staticmethod
    def recalc_and_set(
        *,
        uow,
        company_id: uuid.UUID,
        project_id: uuid.UUID,
        emit_sync: bool = True,
    ) -> bool:
        project = uow.projects.get(company_id=company_id, project_id=project_id)
        if not project:
            return False

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
        lifecycle = ProjectLifecycleStatus(enum_value(project.lifecycle_status))
        is_overdue = bool(
            lifecycle == ProjectLifecycleStatus.ACTIVE
            and project.planned_end_date
            and project.planned_end_date < date.today()
            and has_pending
        )

        health_status = (
            ProjectHealthStatus.BLOCKED
            if has_blocker
            else ProjectHealthStatus.AT_RISK
            if is_overdue
            else ProjectHealthStatus.NORMAL
        )
        legacy_status = (
            ProjectStatus.PROBLEM
            if health_status != ProjectHealthStatus.NORMAL
            else ProjectStatus.OK
        )
        changed = (
            enum_value(project.status) != legacy_status.value
            or enum_value(project.health_status) != health_status.value
        )
        if not changed:
            return False

        project.status = legacy_status
        project.health_status = health_status.value
        uow.projects.save(project)
        if emit_sync:
            uow.sync_change_log.add_change(
                company_id=company_id,
                change_type=SyncChangeType.PROJECT_BASE,
                entity_id=project.id,
                project_id=project.id,
                installer_id=None,
                payload=build_project_sync_payload(project),
            )
        return True
