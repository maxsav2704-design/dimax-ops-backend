from __future__ import annotations

from datetime import datetime, timezone
import uuid

from app.modules.audit.application.service import AuditService
from app.modules.issues.api.schemas import AdminIssueDTO
from app.modules.issues.domain.enums import (
    IssuePriority,
    IssueStatus,
    IssueWorkflowState,
)
from app.shared.domain.errors import NotFound, ValidationError


def _is_overdue(issue) -> bool:
    if issue.status != IssueStatus.OPEN:
        return False
    if issue.due_at is None:
        return False
    due_at = issue.due_at
    if due_at.tzinfo is None:
        due_at = due_at.replace(tzinfo=timezone.utc)
    return due_at < datetime.now(timezone.utc)


def _serialize_issue(issue) -> dict:
    return {
        "id": issue.id,
        "company_id": issue.company_id,
        "door_id": issue.door_id,
        "project_id": issue.door.project_id,
        "door_unit_label": issue.door.unit_label,
        "status": issue.status,
        "workflow_state": issue.workflow_state,
        "priority": issue.priority,
        "owner_user_id": issue.owner_user_id,
        "due_at": issue.due_at,
        "is_overdue": _is_overdue(issue),
        "title": issue.title,
        "details": issue.details,
        "created_at": issue.created_at,
        "updated_at": issue.updated_at,
    }


def _snapshot(issue) -> dict:
    return {
        "door_id": str(issue.door_id),
        "status": issue.status.value if hasattr(issue.status, "value") else str(issue.status),
        "workflow_state": issue.workflow_state.value
        if hasattr(issue.workflow_state, "value")
        else str(issue.workflow_state),
        "priority": issue.priority.value if hasattr(issue.priority, "value") else str(issue.priority),
        "owner_user_id": str(issue.owner_user_id) if issue.owner_user_id else None,
        "due_at": issue.due_at.isoformat() if issue.due_at else None,
        "title": issue.title,
        "details": issue.details,
    }


class IssuesAdminApiService:
    @staticmethod
    def list_issues(
        uow,
        *,
        company_id: uuid.UUID,
        status: IssueStatus | None,
        owner_user_id: uuid.UUID | None,
        workflow_state: IssueWorkflowState | None,
        overdue_only: bool,
        project_id: uuid.UUID | None,
        door_id: uuid.UUID | None,
        limit: int,
        offset: int,
    ) -> list[AdminIssueDTO]:
        rows = uow.issues.list(
            company_id=company_id,
            status=status,
            owner_user_id=owner_user_id,
            workflow_state=workflow_state,
            overdue_only=overdue_only,
            project_id=project_id,
            door_id=door_id,
            limit=limit,
            offset=offset,
        )
        return [AdminIssueDTO(**_serialize_issue(x)) for x in rows]

    @staticmethod
    def get_issue(
        uow,
        *,
        company_id: uuid.UUID,
        issue_id: uuid.UUID,
    ) -> AdminIssueDTO:
        row = uow.issues.get(
            company_id=company_id,
            issue_id=issue_id,
        )
        if row is None:
            raise NotFound("Issue not found", details={"issue_id": str(issue_id)})
        return AdminIssueDTO(**_serialize_issue(row))

    @staticmethod
    def update_issue_status(
        uow,
        *,
        company_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        issue_id: uuid.UUID,
        status: IssueStatus,
        details: str | None,
    ) -> AdminIssueDTO:
        row = uow.issues.get(
            company_id=company_id,
            issue_id=issue_id,
        )
        if row is None:
            raise NotFound("Issue not found", details={"issue_id": str(issue_id)})

        return IssuesAdminApiService._apply_workflow_patch(
            uow,
            company_id=company_id,
            actor_user_id=actor_user_id,
            row=row,
            patch={
                "status": status,
                "details": details,
            },
            action="ISSUE_STATUS_UPDATE",
        )

    @staticmethod
    def update_issue_workflow(
        uow,
        *,
        company_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        issue_id: uuid.UUID,
        patch: dict,
    ) -> AdminIssueDTO:
        row = uow.issues.get(
            company_id=company_id,
            issue_id=issue_id,
        )
        if row is None:
            raise NotFound("Issue not found", details={"issue_id": str(issue_id)})
        if not patch:
            raise ValidationError("at least one field must be provided")

        return IssuesAdminApiService._apply_workflow_patch(
            uow,
            company_id=company_id,
            actor_user_id=actor_user_id,
            row=row,
            patch=patch,
            action="ISSUE_WORKFLOW_UPDATE",
        )

    @staticmethod
    def bulk_update_issue_workflow(
        uow,
        *,
        company_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        issue_ids: list[uuid.UUID],
        patch: dict,
    ) -> dict:
        if not issue_ids:
            raise ValidationError("issue_ids must not be empty")
        if not patch:
            raise ValidationError("at least one field must be provided")

        unique_issue_ids: list[uuid.UUID] = []
        seen: set[uuid.UUID] = set()
        for issue_id in issue_ids:
            value = uuid.UUID(str(issue_id))
            if value in seen:
                continue
            seen.add(value)
            unique_issue_ids.append(value)

        rows = uow.issues.list_by_ids(
            company_id=company_id,
            issue_ids=unique_issue_ids,
        )
        by_id = {row.id: row for row in rows}
        missing = [x for x in unique_issue_ids if x not in by_id]

        items: list[AdminIssueDTO] = []
        for issue_id in unique_issue_ids:
            if issue_id not in by_id:
                continue
            row = by_id[issue_id]
            items.append(
                IssuesAdminApiService._apply_workflow_patch(
                    uow,
                    company_id=company_id,
                    actor_user_id=actor_user_id,
                    row=row,
                    patch=patch,
                    action="ISSUE_WORKFLOW_BULK_UPDATE",
                )
            )

        return {
            "updated": len(items),
            "missing_issue_ids": missing,
            "items": items,
        }

    @staticmethod
    def _apply_workflow_patch(
        uow,
        *,
        company_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        row,
        patch: dict,
        action: str,
    ) -> AdminIssueDTO:
        before = _snapshot(row)

        if "owner_user_id" in patch:
            owner_id = patch.get("owner_user_id")
            if owner_id is None:
                row.owner_user_id = None
            else:
                owner = uow.users.get_by_id(
                    company_id=company_id,
                    user_id=uuid.UUID(str(owner_id)),
                )
                if owner is None:
                    raise ValidationError("owner_user_id not found or inactive")
                row.owner_user_id = owner.id

        if "due_at" in patch:
            due_at = patch.get("due_at")
            if due_at is None:
                row.due_at = None
            else:
                value = due_at
                if value.tzinfo is None:
                    value = value.replace(tzinfo=timezone.utc)
                row.due_at = value

        if "priority" in patch and patch.get("priority") is not None:
            row.priority = IssuePriority(patch["priority"])

        explicit_status = "status" in patch and patch.get("status") is not None
        explicit_workflow = "workflow_state" in patch and patch.get("workflow_state") is not None

        if explicit_status:
            row.status = IssueStatus(patch["status"])
            if row.status == IssueStatus.CLOSED and not explicit_workflow:
                row.workflow_state = IssueWorkflowState.CLOSED
            if row.status == IssueStatus.OPEN and row.workflow_state == IssueWorkflowState.CLOSED and not explicit_workflow:
                row.workflow_state = IssueWorkflowState.NEW

        if explicit_workflow:
            wf = IssueWorkflowState(patch["workflow_state"])
            row.workflow_state = wf
            if wf == IssueWorkflowState.CLOSED:
                row.status = IssueStatus.CLOSED
            elif row.status == IssueStatus.CLOSED and not explicit_status:
                row.status = IssueStatus.OPEN

        if "details" in patch:
            details = patch.get("details")
            if details is None:
                row.details = None
            else:
                text = str(details).strip()
                row.details = text if text else None

        uow.issues.save(row)

        AuditService.add(
            uow,
            company_id=company_id,
            actor_user_id=actor_user_id,
            entity_type="issue",
            entity_id=row.id,
            action=action,
            before=before,
            after=_snapshot(row),
        )
        uow.session.flush()
        return AdminIssueDTO(**_serialize_issue(row))
