from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class OutboxItemDTO(BaseModel):
    id: UUID
    correlation_id: UUID | None
    channel: str
    recipient: str | None
    subject: str | None
    template_id: str | None
    template_code: str | None
    template_name: str | None
    message_preview: str | None
    attachment_name: str | None
    status: str
    scheduled_at: datetime
    max_attempts: int
    last_error: str | None
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


class OutboxSummaryResponse(BaseModel):
    total: int
    by_channel: dict[str, int]
    by_status: dict[str, int]
    by_delivery_status: dict[str, int]
    pending_overdue_15m: int
    failed_total: int


class OutboxRetryBody(BaseModel):
    reason: str | None = None


class OutboxRetryResponse(BaseModel):
    item: OutboxItemDTO
