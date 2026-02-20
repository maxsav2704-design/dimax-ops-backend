from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class OutboxItemDTO(BaseModel):
    id: UUID
    channel: str
    status: str
    provider_message_id: str | None
    provider_status: str | None
    provider_error: str | None
    attempts: int
    created_at: datetime
    sent_at: datetime | None
    delivery_status: str
    delivered_at: datetime | None


class OutboxListResponse(BaseModel):
    items: list[OutboxItemDTO]
