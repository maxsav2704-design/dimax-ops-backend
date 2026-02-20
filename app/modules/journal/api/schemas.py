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


class JournalDetailsResponse(BaseModel):
    id: UUID
    project_id: UUID
    status: str
    title: str | None
    notes: str | None
    public_token: str | None
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


class OkResponse(BaseModel):
    ok: bool = True
