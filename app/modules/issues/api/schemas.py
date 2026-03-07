from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.issues.domain.enums import IssuePriority, IssueStatus, IssueWorkflowState


class AdminIssueDTO(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    door_id: uuid.UUID
    project_id: uuid.UUID
    door_unit_label: str
    status: IssueStatus
    workflow_state: IssueWorkflowState
    priority: IssuePriority
    owner_user_id: uuid.UUID | None
    due_at: datetime | None
    is_overdue: bool
    title: str | None
    details: str | None
    created_at: datetime
    updated_at: datetime


class AdminIssuesListResponse(BaseModel):
    items: list[AdminIssueDTO]


class AdminIssueStatusUpdateBody(BaseModel):
    status: IssueStatus
    details: str | None = Field(default=None, max_length=2000)


class AdminIssueWorkflowUpdateBody(BaseModel):
    status: IssueStatus | None = None
    workflow_state: IssueWorkflowState | None = None
    priority: IssuePriority | None = None
    owner_user_id: uuid.UUID | None = None
    due_at: datetime | None = None
    details: str | None = Field(default=None, max_length=2000)


class AdminIssueBulkWorkflowUpdateBody(BaseModel):
    issue_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    status: IssueStatus | None = None
    workflow_state: IssueWorkflowState | None = None
    priority: IssuePriority | None = None
    owner_user_id: uuid.UUID | None = None
    due_at: datetime | None = None
    details: str | None = Field(default=None, max_length=2000)


class AdminIssuesBulkWorkflowUpdateResponse(BaseModel):
    updated: int
    missing_issue_ids: list[uuid.UUID]
    items: list[AdminIssueDTO]
