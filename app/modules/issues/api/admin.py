from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query

from app.api.v1.deps import CurrentUser, get_uow, require_admin
from app.modules.issues.api.schemas import (
    AdminIssueDTO,
    AdminIssueBulkWorkflowUpdateBody,
    AdminIssuesBulkWorkflowUpdateResponse,
    AdminIssueWorkflowUpdateBody,
    AdminIssuesListResponse,
    AdminIssueStatusUpdateBody,
)
from app.modules.issues.application.admin_api_service import (
    IssuesAdminApiService,
)
from app.modules.issues.domain.enums import IssueStatus, IssueWorkflowState
from app.shared.infrastructure.db.uow_sqlalchemy import SqlAlchemyUnitOfWork

router = APIRouter(prefix="/admin/issues", tags=["Admin / Issues"])


@router.get("", response_model=AdminIssuesListResponse)
def list_issues(
    status: IssueStatus | None = Query(default=None),
    owner_user_id: uuid.UUID | None = Query(default=None),
    workflow_state: IssueWorkflowState | None = Query(default=None),
    overdue_only: bool = Query(default=False),
    project_id: uuid.UUID | None = Query(default=None),
    door_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: CurrentUser = Depends(require_admin),
) -> AdminIssuesListResponse:
    with uow:
        items = IssuesAdminApiService.list_issues(
            uow,
            company_id=current_user.company_id,
            status=status,
            owner_user_id=owner_user_id,
            workflow_state=workflow_state,
            overdue_only=overdue_only,
            project_id=project_id,
            door_id=door_id,
            limit=limit,
            offset=offset,
        )
        return AdminIssuesListResponse(items=items)


@router.patch("/workflow/bulk", response_model=AdminIssuesBulkWorkflowUpdateResponse)
def bulk_update_issue_workflow(
    body: AdminIssueBulkWorkflowUpdateBody,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: CurrentUser = Depends(require_admin),
) -> AdminIssuesBulkWorkflowUpdateResponse:
    with uow:
        payload = body.model_dump(exclude_unset=True)
        issue_ids = payload.pop("issue_ids", [])
        result = IssuesAdminApiService.bulk_update_issue_workflow(
            uow,
            company_id=current_user.company_id,
            actor_user_id=current_user.id,
            issue_ids=issue_ids,
            patch=payload,
        )
        return AdminIssuesBulkWorkflowUpdateResponse(**result)


@router.get("/{issue_id}", response_model=AdminIssueDTO)
def get_issue(
    issue_id: uuid.UUID,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: CurrentUser = Depends(require_admin),
) -> AdminIssueDTO:
    with uow:
        return IssuesAdminApiService.get_issue(
            uow,
            company_id=current_user.company_id,
            issue_id=issue_id,
        )


@router.patch("/{issue_id}/status", response_model=AdminIssueDTO)
def update_issue_status(
    issue_id: uuid.UUID,
    body: AdminIssueStatusUpdateBody,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: CurrentUser = Depends(require_admin),
) -> AdminIssueDTO:
    with uow:
        return IssuesAdminApiService.update_issue_status(
            uow,
            company_id=current_user.company_id,
            actor_user_id=current_user.id,
            issue_id=issue_id,
            status=body.status,
            details=body.details,
        )


@router.patch("/{issue_id}/workflow", response_model=AdminIssueDTO)
def update_issue_workflow(
    issue_id: uuid.UUID,
    body: AdminIssueWorkflowUpdateBody,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: CurrentUser = Depends(require_admin),
) -> AdminIssueDTO:
    with uow:
        return IssuesAdminApiService.update_issue_workflow(
            uow,
            company_id=current_user.company_id,
            actor_user_id=current_user.id,
            issue_id=issue_id,
            patch=body.model_dump(exclude_unset=True),
        )
