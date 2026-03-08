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


class OutboxWebhookSignalSummaryResponse(BaseModel):
    window_hours: int
    total_received: int
    updated_total: int
    duplicate_total: int
    unmatched_total: int
    provider_failed_total: int


class OutboxWebhookSignalItemDTO(BaseModel):
    id: UUID
    provider: str
    event_type: str
    external_id: str | None
    result: str
    status: str | None
    error: str | None
    outbox_id: str | None
    created_at: datetime


class OutboxWebhookSignalListResponse(BaseModel):
    items: list[OutboxWebhookSignalItemDTO]


class OutboxRetryBody(BaseModel):
    reason: str | None = None


class OutboxRetryResponse(BaseModel):
    item: OutboxItemDTO


class OutboxBulkRetryBody(BaseModel):
    outbox_ids: list[UUID]
    reason: str | None = None


class OutboxBulkRetryItemDTO(BaseModel):
    outbox_id: UUID
    status: str
    error: str | None = None
    item: OutboxItemDTO | None = None


class OutboxBulkRetryResponse(BaseModel):
    items: list[OutboxBulkRetryItemDTO]
    total_messages: int
    successful_messages: int
    failed_messages: int
    skipped_messages: int


class OutboxRetryAuditItemDTO(BaseModel):
    id: UUID
    outbox_id: UUID
    actor_user_id: UUID
    reason: str | None = None
    before_status: str | None = None
    after_status: str | None = None
    before_delivery_status: str | None = None
    after_delivery_status: str | None = None
    created_at: datetime


class OutboxRetryAuditListResponse(BaseModel):
    items: list[OutboxRetryAuditItemDTO]
