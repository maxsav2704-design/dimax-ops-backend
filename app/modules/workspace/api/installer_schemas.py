from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


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
    today_tasks: list[InstallerWorkspaceEventDTO]
    priority_tasks: list[InstallerWorkspacePriorityDoorDTO]
    problem_projects: list[InstallerWorkspaceProblemProjectDTO]
    earnings_today: str
