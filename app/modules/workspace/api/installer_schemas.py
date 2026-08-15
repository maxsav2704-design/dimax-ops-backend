from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.calendar.api.schemas import EventDTO
from app.modules.earnings.api.installer_schemas import InstallerEarningsSummaryDTO
from app.modules.issues.api.installer_schemas import InstallerIssueReportDTO
from app.modules.projects.api.installer_schemas import InstallerProjectListItem
from app.modules.sync.api.installer_schemas import InstallerSyncQueueListResponse


class InstallerWorkspaceEventDTO(BaseModel):
    id: uuid.UUID
    title: str
    starts_at: datetime
    ends_at: datetime
    project_id: uuid.UUID | None = None


class InstallerWorkspacePriorityDoorDTO(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    unit_label: str
    status: str
    is_critical: bool


class InstallerWorkspaceProblemProjectDTO(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    address: str
    health_status: str


class InstallerWorkspaceResponse(BaseModel):
    projects: list[InstallerProjectListItem] = Field(default_factory=list)
    events: list[EventDTO] = Field(default_factory=list)
    task_events: list[EventDTO] = Field(default_factory=list)
    issues: list[InstallerIssueReportDTO] = Field(default_factory=list)
    earnings_summary: InstallerEarningsSummaryDTO | None = None
    sync_queue: InstallerSyncQueueListResponse | None = None
    today_tasks: list[InstallerWorkspaceEventDTO] = Field(default_factory=list)
    priority_tasks: list[InstallerWorkspacePriorityDoorDTO] = Field(default_factory=list)
    problem_projects: list[InstallerWorkspaceProblemProjectDTO] = Field(default_factory=list)
    earnings_today: str = "0.00"
