from __future__ import annotations

import uuid

from sqlalchemy import Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.infrastructure.db.base import (
    Base,
    UUIDPrimaryKeyMixin,
    TimestampMixin,
)


class WebhookEventORM(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "webhook_events"
    __table_args__ = (
        Index("ix_webhook_events_provider", "provider"),
        Index("ix_webhook_events_external_id", "external_id"),
        Index("ix_webhook_events_created_at", "created_at"),
    )

    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
