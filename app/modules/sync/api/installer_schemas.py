from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.api.v1.pagination import PaginationDTO


class SyncEventIn(BaseModel):
    client_event_id: str = Field(min_length=8, max_length=80)
    type: Literal["DOOR_SET_STATUS", "ADDON_FACT_CREATE"]
    project_id: UUID
    happened_at: datetime | None = None
    payload: dict[str, Any]


class InstallerSyncRequest(BaseModel):
    since_cursor: int = 0
    ack_cursor: int = 0
    events: list[SyncEventIn] = Field(default_factory=list, max_length=500)

    app_version: str | None = None
    device_id: str | None = None


class SyncAckItem(BaseModel):
    client_event_id: str
    ok: bool
    applied: bool
    error: str | None = None


class SyncChangeDTO(BaseModel):
    cursor_id: int
    change_type: str
    payload: dict


class ColdSnapshotProjectDTO(BaseModel):
    id: UUID
    name: str
    address: str | None
    status: str
    waze_url: str | None


class ColdSnapshotDTO(BaseModel):
    projects: list[ColdSnapshotProjectDTO]
    doors: list[dict]
    door_types: list[dict]
    reasons: list[dict]
    addon_types: list[dict]
    addon_plans: list[dict]
    addon_facts: list[dict]


class InstallerSyncResponse(BaseModel):
    server_time: datetime
    next_cursor: int
    reset_required: bool = False
    snapshot: ColdSnapshotDTO | None = None

    acks: list[SyncAckItem]

    changes: list[SyncChangeDTO]


class InstallerSyncQueueItemDTO(BaseModel):
    id: UUID
    entity_type: str
    entity_id: UUID
    operation_type: str
    payload: dict[str, Any]
    base_version: int
    status: str
    conflict_code: str | None = None
    created_at: datetime
    synced_at: datetime | None = None


class InstallerSyncQueueListResponse(BaseModel):
    items: list[InstallerSyncQueueItemDTO]
    pagination: PaginationDTO
