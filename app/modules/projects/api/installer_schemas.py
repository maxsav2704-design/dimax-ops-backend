from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel

from app.api.v1.pagination import PaginationDTO


class AddonTypeMiniDTO(BaseModel):
    id: UUID
    name: str
    unit: str


class AddonPlanDTO(BaseModel):
    addon_type_id: UUID
    qty_planned: Decimal


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


class DoorTypeMiniDTO(BaseModel):
    id: UUID
    code: str
    name: str


class ReasonMiniDTO(BaseModel):
    id: UUID
    code: str
    name: str


class InstallerProjectListItem(BaseModel):
    id: UUID
    name: str
    address: str
    status: str
    waze_url: str | None


class InstallerProjectListResponse(BaseModel):
    items: list[InstallerProjectListItem]
    pagination: PaginationDTO


class InstallerDoorDTO(BaseModel):
    id: UUID
    unit_label: str
    door_type_id: UUID
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


class InstallerIssueDTO(BaseModel):
    id: UUID
    door_id: UUID
    status: str
    title: str | None
    details: str | None


class InstallerProjectAddressDetailsDTO(BaseModel):
    street: str | None = None
    building: str | None = None
    city: str | None = None
    entrance: str | None = None
    lat: Decimal | None = None
    lng: Decimal | None = None
    waze_url: str | None = None
    waze_deep_link: str | None = None


class InstallerProjectDeveloperDetailsDTO(BaseModel):
    name: str | None = None
    contact_name: str | None = None
    phone: str | None = None
    phone_alt: str | None = None
    whatsapp: str | None = None
    notes: str | None = None
    whatsapp_deep_link: str | None = None
    call_deep_link: str | None = None


class InstallerProjectDetailsResponse(BaseModel):
    id: UUID
    name: str
    address: str | None
    address_details: InstallerProjectAddressDetailsDTO | None = None
    waze_url: str | None
    whatsapp_url: str | None = None
    call_url: str | None = None
    developer: InstallerProjectDeveloperDetailsDTO | None = None
    contact_name: str | None = None
    contact_phone: str | None = None
    developer_phone_alt: str | None = None
    developer_whatsapp: str | None = None
    developer_company: str | None = None
    developer_notes: str | None = None
    status: str
    doors: list[InstallerDoorDTO]
    issues_open: list[InstallerIssueDTO]
    door_types_catalog: list[DoorTypeMiniDTO]
    reasons_catalog: list[ReasonMiniDTO]
    addons: InstallerProjectAddonsDTO
    server_time: datetime
