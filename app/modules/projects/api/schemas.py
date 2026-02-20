from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class ProjectCreateBody(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    address: str = Field(min_length=2, max_length=400)
    developer_company: str | None = Field(default=None, max_length=200)
    contact_name: str | None = Field(default=None, max_length=200)
    contact_phone: str | None = Field(default=None, max_length=40)
    contact_email: str | None = Field(default=None, max_length=255)


class ProjectUpdateBody(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    address: str | None = Field(default=None, max_length=400)
    developer_company: str | None = Field(default=None, max_length=200)
    contact_name: str | None = Field(default=None, max_length=200)
    contact_phone: str | None = Field(default=None, max_length=40)
    contact_email: str | None = Field(default=None, max_length=255)


class ProjectListItem(BaseModel):
    id: UUID
    name: str
    address: str
    status: str


class ProjectListResponse(BaseModel):
    items: list[ProjectListItem]


class DoorImportRow(BaseModel):
    door_type_id: UUID
    unit_label: str = Field(min_length=1, max_length=120)
    our_price: Decimal = Field(ge=0)


class ImportDoorsBody(BaseModel):
    rows: list[DoorImportRow] = Field(min_length=1, max_length=5000)


class AssignInstallerBody(BaseModel):
    installer_id: UUID


class DoorDTO(BaseModel):
    id: UUID
    unit_label: str
    door_type_id: UUID
    our_price: Decimal
    status: str
    installer_id: UUID | None
    reason_id: UUID | None
    comment: str | None
    is_locked: bool


class IssueDTO(BaseModel):
    id: UUID
    door_id: UUID
    status: str
    title: str | None
    details: str | None


class ProjectDetailsResponse(BaseModel):
    id: UUID
    name: str
    address: str
    status: str
    developer_company: str | None
    contact_name: str | None
    contact_phone: str | None
    contact_email: str | None
    doors: list[DoorDTO]
    issues_open: list[IssueDTO]


class OkResponse(BaseModel):
    ok: bool = True
