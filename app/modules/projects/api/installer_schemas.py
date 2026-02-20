from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class AddonTypeMiniDTO(BaseModel):
    id: UUID
    name: str
    unit: str


class AddonPlanDTO(BaseModel):
    addon_type_id: UUID
    qty_planned: Decimal
    client_price: Decimal
    installer_price: Decimal


class AddonFactDTO(BaseModel):
    id: UUID
    addon_type_id: UUID
    qty_done: Decimal
    done_at: datetime
    comment: str | None
    source: str


class InstallerProjectAddonsDTO(BaseModel):
    types: list[AddonTypeMiniDTO]
    plan: list[AddonPlanDTO]
    facts: list[AddonFactDTO]


class InstallerProjectListItem(BaseModel):
    id: UUID
    name: str
    address: str
    status: str


class InstallerProjectListResponse(BaseModel):
    items: list[InstallerProjectListItem]


class InstallerDoorDTO(BaseModel):
    id: UUID
    unit_label: str
    door_type_id: UUID
    our_price: Decimal
    status: str
    reason_id: UUID | None
    comment: str | None
    is_locked: bool


class InstallerIssueDTO(BaseModel):
    id: UUID
    door_id: UUID
    status: str
    title: str | None
    details: str | None


class InstallerProjectDetailsResponse(BaseModel):
    id: UUID
    name: str
    address: str | None
    status: str
    doors: list[InstallerDoorDTO]
    issues_open: list[InstallerIssueDTO]
    addons: InstallerProjectAddonsDTO
    server_time: datetime
