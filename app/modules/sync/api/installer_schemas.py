from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.api.v1.pagination import PaginationDTO


class SyncEventIn(BaseModel):
    client_event_id: str = Field(min_length=8, max_length=80)
    type: Literal["DOOR_SET_STATUS", "ADDON_FACT_CREATE", "ISSUE_CREATE"]
    project_id: UUID
    happened_at: datetime | None = None
    payload: dict[str, Any]


class InstallerSyncRequest(BaseModel):
    since_cursor: int = Field(default=0, ge=0)
    ack_cursor: int = Field(default=0, ge=0)
    events: list[SyncEventIn] = Field(default_factory=list, max_length=500)

    app_version: str | None = None
    device_id: str | None = None


class InstallerSyncBatchItemIn(BaseModel):
    id: UUID
    entity_type: str = Field(min_length=1, max_length=64)
    entity_id: UUID
    operation_type: Literal["DOOR_SET_STATUS", "ADDON_FACT_CREATE"]
    project_id: UUID
    payload: dict[str, Any]
    base_version: int = Field(ge=0)
    happened_at: datetime | None = None


class InstallerSyncBatchRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=255)
    items: list[InstallerSyncBatchItemIn] = Field(
        default_factory=list,
        max_length=500,
    )
    app_version: str | None = Field(default=None, max_length=40)


class InstallerSyncBatchResultDTO(BaseModel):
    item_id: UUID
    status: Literal["APPLIED", "CONFLICT", "AUTH_REQUIRED"]
    new_version: int | None = None
    conflict_code: str | None = None
    message: str | None = None


class InstallerSyncBatchResponse(BaseModel):
    server_time: datetime
    results: list[InstallerSyncBatchResultDTO]


class SyncAckItem(BaseModel):
    client_event_id: str
    ok: bool
    applied: bool
    error: str | None = None


class SyncChangeDTO(BaseModel):
    cursor_id: int
    change_type: str
    payload: dict


class _StrictSnapshotDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ColdSnapshotProjectDTO(_StrictSnapshotDTO):
    id: UUID
    name: str
    address: str | None
    status: str
    lifecycle_status: str
    health_status: str
    waze_url: str | None
    updated_at: datetime | None = None


class ColdSnapshotDoorDTO(_StrictSnapshotDTO):
    id: UUID
    project_id: UUID
    door_type_id: UUID
    unit_label: str
    order_number: str | None
    house_number: str | None
    floor_label: str | None
    apartment_number: str | None
    location_code: str | None
    door_marking: str | None
    status: str
    reason_id: UUID | None
    comment: str | None
    is_locked: bool
    version: int
    updated_at: datetime | None = None


class ColdSnapshotDoorTypeDTO(_StrictSnapshotDTO):
    id: UUID
    code: str
    name: str


class ColdSnapshotReasonDTO(_StrictSnapshotDTO):
    id: UUID
    code: str
    name: str


class ColdSnapshotAddonTypeDTO(_StrictSnapshotDTO):
    id: UUID
    name: str
    unit: str


class ColdSnapshotAddonPlanDTO(_StrictSnapshotDTO):
    project_id: UUID
    addon_type_id: UUID
    qty_planned: Decimal


class ColdSnapshotAddonFactDTO(_StrictSnapshotDTO):
    id: UUID
    project_id: UUID
    addon_type_id: UUID
    installer_id: UUID | None = None
    qty_done: Decimal
    done_at: datetime
    comment: str | None
    source: str
    updated_at: datetime | None = None


class ColdSnapshotIssueDTO(_StrictSnapshotDTO):
    id: UUID
    door_id: UUID
    project_id: UUID
    status: str
    title: str | None
    details: str | None


class ColdSnapshotDTO(BaseModel):
    projects: list[ColdSnapshotProjectDTO]
    doors: list[ColdSnapshotDoorDTO]
    door_types: list[ColdSnapshotDoorTypeDTO]
    reasons: list[ColdSnapshotReasonDTO]
    addon_types: list[ColdSnapshotAddonTypeDTO]
    addon_plans: list[ColdSnapshotAddonPlanDTO]
    addon_facts: list[ColdSnapshotAddonFactDTO]
    issues: list[ColdSnapshotIssueDTO]


class InstallerSyncResponse(BaseModel):
    server_time: datetime
    next_cursor: int
    reset_required: bool = False
    snapshot: ColdSnapshotDTO | None = None

    acks: list[SyncAckItem]

    changes: list[SyncChangeDTO]


class InstallerSyncQueueItemDTO(BaseModel):
    id: UUID
    project_id: UUID | None = None
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
