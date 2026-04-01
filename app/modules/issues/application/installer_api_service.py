from __future__ import annotations

import uuid

from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.domain.errors import DoorNotAssigned
from app.modules.doors.infrastructure.history_models import DoorStatusHistoryORM
from app.modules.issues.api.installer_schemas import InstallerIssueDTO
from app.modules.issues.domain.enums import IssuePriority, IssueStatus, IssueWorkflowState
from app.modules.issues.infrastructure.models import IssueORM
from app.modules.projects.application.status_service import ProjectStatusService
from app.shared.domain.errors import NotFound


class InstallerIssuesApiService:
    @staticmethod
    def list_issues(
        uow,
        *,
        company_id: uuid.UUID,
        created_by_user_id: uuid.UUID,
    ) -> list[InstallerIssueDTO]:
        rows = uow.issues.list_created_by_user(
            company_id=company_id,
            created_by_user_id=created_by_user_id,
        )
        items: list[InstallerIssueDTO] = []
        for row in rows:
            door = uow.doors.get(company_id=company_id, door_id=row.door_id)
            if not door:
                continue
            items.append(
                InstallerIssueDTO(
                    id=row.id,
                    door_id=row.door_id,
                    project_id=door.project_id,
                    status=row.status.value if hasattr(row.status, "value") else str(row.status),
                    workflow_state=(
                        row.workflow_state.value
                        if hasattr(row.workflow_state, "value")
                        else str(row.workflow_state)
                    ),
                    title=row.title,
                    details=row.details,
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                )
            )
        return items

    @staticmethod
    def create_issue(
        uow,
        *,
        company_id: uuid.UUID,
        installer_id: uuid.UUID,
        created_by_user_id: uuid.UUID,
        door_id: uuid.UUID,
        title: str | None,
        details: str | None,
    ) -> InstallerIssueDTO:
        door = uow.doors.get(company_id=company_id, door_id=door_id)
        if not door:
            raise NotFound("Door not found", details={"door_id": str(door_id)})
        if getattr(door, "installer_id", None) != installer_id:
            raise DoorNotAssigned(
                "Door is not assigned to this installer",
                details={"door_id": str(door_id)},
            )

        issue = uow.issues.get_by_door(company_id=company_id, door_id=door_id)
        if issue is None:
            issue = IssueORM(
                company_id=company_id,
                door_id=door_id,
                status=IssueStatus.OPEN,
                workflow_state=IssueWorkflowState.NEW,
                priority=IssuePriority.P3,
                title=title,
                details=details,
                created_by_user_id=created_by_user_id,
                owner_user_id=created_by_user_id,
            )
        else:
            issue.status = IssueStatus.OPEN
            issue.workflow_state = IssueWorkflowState.NEW
            issue.priority = IssuePriority.P3
            issue.title = title
            issue.details = details
            issue.created_by_user_id = created_by_user_id
            issue.owner_user_id = created_by_user_id

        uow.issues.save(issue)

        old_status = getattr(door, "status", None)
        door.status = DoorStatus.ISSUE_OPEN
        door.version = int(getattr(door, "version", 0) or 0) + 1
        uow.doors.save(door)
        uow.session.add(
            DoorStatusHistoryORM(
                company_id=company_id,
                door_id=door.id,
                changed_by_user_id=created_by_user_id,
                from_status=old_status.value if hasattr(old_status, "value") else str(old_status),
                to_status=DoorStatus.ISSUE_OPEN.value,
                source="MOBILE",
            )
        )

        ProjectStatusService.recalc_and_set(
            uow=uow,
            company_id=company_id,
            project_id=door.project_id,
        )
        uow.session.flush()

        return InstallerIssueDTO(
            id=issue.id,
            door_id=issue.door_id,
            project_id=door.project_id,
            status=issue.status.value,
            workflow_state=issue.workflow_state.value,
            title=issue.title,
            details=issue.details,
            created_at=issue.created_at,
            updated_at=issue.updated_at,
        )
