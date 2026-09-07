from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.api.v1.pagination import PaginationDTO


class InstallerIssueReportDTO(BaseModel):
    id: uuid.UUID
    door_id: uuid.UUID
    project_id: uuid.UUID
    status: str
    workflow_state: str
    title: str | None
    details: str | None
    created_at: datetime
    updated_at: datetime


class InstallerIssuesListResponse(BaseModel):
    items: list[InstallerIssueReportDTO]
    pagination: PaginationDTO


class InstallerIssueCreateBody(BaseModel):
    door_id: uuid.UUID
    title: str | None = Field(default=None, max_length=200)
    details: str | None = Field(default=None, max_length=2000)


class InstallerIssueUpdateBody(BaseModel):
    comment: str | None = Field(default=None, max_length=2000)
