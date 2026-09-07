from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class JournalCreateBody(BaseModel):
    project_id: UUID
    title: str | None = Field(default=None, max_length=200)


class JournalListItem(BaseModel):
    id: UUID
    project_id: UUID
    status: str
    title: str | None
    signed_at: str | None


class JournalListResponse(BaseModel):
    items: list[JournalListItem]


class JournalCreateResponse(BaseModel):
    id: UUID


class JournalDetailsResponse(BaseModel):
    id: UUID
    project_id: UUID
    status: str
    title: str | None
    notes: str | None
    public_token: str | None
    public_token_expires_at: datetime | None
    lock_header: bool
    lock_table: bool
    lock_footer: bool
    signed_at: str | None
    signer_name: str | None
    snapshot_version: int

    email_delivery_status: str
    whatsapp_delivery_status: str
    email_last_sent_at: datetime | None
    whatsapp_last_sent_at: datetime | None
    whatsapp_delivered_at: datetime | None
    email_last_error: str | None
    whatsapp_last_error: str | None


class JournalUpdateBody(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=5000)
    lock_header: bool | None = None
    lock_table: bool | None = None
    lock_footer: bool | None = None


class PublicSignBody(BaseModel):
    signer_name: str = Field(min_length=2, max_length=200)
    signature_payload: dict


class PublicJournalDTO(BaseModel):
    id: UUID
    project_id: UUID
    status: str
    title: str | None
    notes: str | None
    lock_header: bool
    lock_table: bool
    lock_footer: bool
    signed_at: str | None
    signer_name: str | None
    snapshot_version: int


class PublicJournalItemDTO(BaseModel):
    unit_label: str
    door_type_id: UUID
    door_type_name: str
    installed_at: str | None


class PublicJournalAddonItemDTO(BaseModel):
    name: str
    quantity: str
    unit: str
    done_at: str
    comment: str | None


class PublicJournalProjectDTO(BaseModel):
    name: str
    address: str | None
    developer_company: str | None
    contact_name: str | None


class PublicJournalGetResponse(BaseModel):
    journal: PublicJournalDTO
    project: PublicJournalProjectDTO
    items: list[PublicJournalItemDTO]
    addon_items: list[PublicJournalAddonItemDTO]


class JournalMarkReadyResponse(BaseModel):
    public_token: str
    public_url: str
    signing_url: str


class JournalExportPdfResponse(BaseModel):
    file_path: str
    size_bytes: int


class OkResponse(BaseModel):
    ok: bool = True


class PublicSignResponse(BaseModel):
    ok: bool = True
    pdf_ready: bool
    email_queued: bool
