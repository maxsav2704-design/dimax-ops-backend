from __future__ import annotations

import uuid

from app.modules.doors.application.transition_recorder import record_door_transition
from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.domain.errors import DoorNotAssigned
from app.modules.issues.api.installer_schemas import InstallerIssueReportDTO
from app.modules.issues.domain.enums import IssuePriority, IssueStatus, IssueWorkflowState
from app.modules.issues.infrastructure.models import IssueORM
from app.modules.projects.application.status_service import ProjectStatusService
from app.shared.domain.errors import NotFound


class InstallerIssuesApiService:
    @staticmethod
    def ensure_issue_visible(
        uow,
        *,
        company_id: uuid.UUID,
        installer_id: uuid.UUID,
        user_id: uuid.UUID,
        issue_id: uuid.UUID,
    ) -> tuple[IssueORM, object]:
        issue = uow.issues.get(company_id=company_id, issue_id=issue_id)
        if issue is None:
            raise NotFound("Issue not found", details={"issue_id": str(issue_id)})
        door = uow.doors.get(company_id=company_id, door_id=issue.door_id)
        if door is None:
            raise NotFound("Door not found", details={"door_id": str(issue.door_id)})
        is_assigned = getattr(door, "installer_id", None) == installer_id
        is_author = issue.created_by_user_id == user_id
        if not is_assigned and not is_author:
            raise DoorNotAssigned(
                "Issue is not assigned to this installer",
                details={"issue_id": str(issue_id)},
            )
        return issue, door

    @staticmethod
    def list_issues(
        uow,
        *,
        company_id: uuid.UUID,
        created_by_user_id: uuid.UUID,
    ) -> list[InstallerIssueReportDTO]:
        rows = uow.issues.list_created_by_user(
            company_id=company_id,
            created_by_user_id=created_by_user_id,
        )
        items: list[InstallerIssueReportDTO] = []
        for row in rows:
            door = uow.doors.get(company_id=company_id, door_id=row.door_id)
            if not door:
                continue
            items.append(
                InstallerIssueReportDTO(
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
        source: str = "MOBILE_API",
    ) -> InstallerIssueReportDTO:
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

        ProjectStatusService.recalc_and_set(
            uow=uow,
            company_id=company_id,
            project_id=door.project_id,
        )
        record_door_transition(
            uow,
            company_id=company_id,
            actor_user_id=created_by_user_id,
            door=door,
            from_status=old_status,
            source=source,
            reason=title or details,
        )
        uow.session.flush()

        return InstallerIssueReportDTO(
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

    @staticmethod
    def update_issue_comment(
        uow,
        *,
        company_id: uuid.UUID,
        installer_id: uuid.UUID,
        user_id: uuid.UUID,
        issue_id: uuid.UUID,
        comment: str | None,
    ) -> InstallerIssueReportDTO:
        issue, door = InstallerIssuesApiService.ensure_issue_visible(
            uow,
            company_id=company_id,
            installer_id=installer_id,
            user_id=user_id,
            issue_id=issue_id,
        )

        text = str(comment or "").strip()
        issue.details = text or None
        uow.issues.save(issue)
        uow.session.flush()

        return InstallerIssueReportDTO(
            id=issue.id,
            door_id=issue.door_id,
            project_id=door.project_id,
            status=issue.status.value if hasattr(issue.status, "value") else str(issue.status),
            workflow_state=(
                issue.workflow_state.value
                if hasattr(issue.workflow_state, "value")
                else str(issue.workflow_state)
            ),
            title=issue.title,
            details=issue.details,
            created_at=issue.created_at,
            updated_at=issue.updated_at,
        )
