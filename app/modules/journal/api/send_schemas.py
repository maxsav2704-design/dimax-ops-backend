from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class SendJournalBody(BaseModel):
    template_id: UUID | None = None
    email_to: EmailStr | None = None
    whatsapp_to: str | None = Field(
        default=None, description="E.164 like +9725xxxxxxx"
    )
    subject: str | None = Field(default=None, max_length=200)
    message: str | None = Field(default=None, max_length=2000)

    send_email: bool = True
    send_whatsapp: bool = True


class SendJournalEnqueuedResponse(BaseModel):
    email: bool
    whatsapp: bool


class SendJournalOutboxIdsResponse(BaseModel):
    email: str | None
    whatsapp: str | None


class SendJournalResponse(BaseModel):
    ok: bool
    enqueued: SendJournalEnqueuedResponse
    outbox_ids: SendJournalOutboxIdsResponse
    public_url: str | None
    object_key: str
