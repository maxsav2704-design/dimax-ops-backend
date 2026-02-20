from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.infrastructure.db.base import (
    Base,
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    TenantMixin,
)
from app.modules.outbox.domain.enums import (
    DeliveryStatus,
    OutboxChannel,
    OutboxStatus,
)


class OutboxMessageORM(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin):
    __tablename__ = "outbox_messages"

    channel: Mapped[OutboxChannel] = mapped_column(
        Enum(OutboxChannel, name="outbox_channel"),
        nullable=False,
        index=True,
    )
    status: Mapped[OutboxStatus] = mapped_column(
        Enum(OutboxStatus, name="outbox_status"),
        nullable=False,
        default=OutboxStatus.PENDING,
        index=True,
    )

    correlation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    provider_message_id: Mapped[str | None] = mapped_column(
        String(120), nullable=True
    )
    provider_status: Mapped[str | None] = mapped_column(
        String(40), nullable=True
    )
    provider_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    delivery_status: Mapped[DeliveryStatus] = mapped_column(
        Enum(DeliveryStatus, name="outbox_delivery_status"),
        nullable=False,
        default=DeliveryStatus.PENDING,
        index=True,
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
