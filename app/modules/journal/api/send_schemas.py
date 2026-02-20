from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class SendJournalBody(BaseModel):
    email_to: EmailStr | None = None
    whatsapp_to: str | None = Field(
        default=None, description="E.164 like +9725xxxxxxx"
    )
    subject: str | None = Field(default=None, max_length=200)
    message: str | None = Field(default=None, max_length=2000)

    send_email: bool = True
    send_whatsapp: bool = True
