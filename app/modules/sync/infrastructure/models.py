from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, Integer, Sequence, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.sync.domain.enums import SyncChangeType, SyncEventType
from app.shared.infrastructure.db.base import (
    Base,
    TenantMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class SyncEventORM(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin):
    __tablename__ = "sync_events"

    installer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )

    event_type: Mapped[SyncEventType] = mapped_column(
        Enum(SyncEventType, name="sync_event_type"), nullable=False
    )
    client_event_id: Mapped[str] = mapped_column(String(80), nullable=False)
    client_happened_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    applied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    apply_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class SyncChangeLogORM(Base, TenantMixin):
    __tablename__ = "sync_change_log"

    cursor_id: Mapped[int | None] = mapped_column(
        BigInteger,
        primary_key=True,
        nullable=False,
        server_default=Sequence("sync_cursor_seq").next_value(),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    change_type: Mapped[SyncChangeType] = mapped_column(
        Enum(SyncChangeType, name="sync_change_type"), nullable=False
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    installer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)


class InstallerSyncStateORM(
    Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin
):
    __tablename__ = "installer_sync_state"

    installer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )

    last_cursor_ack: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    app_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    device_id: Mapped[str | None] = mapped_column(String(80), nullable=True)

    health_status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="OK"
    )
    health_lag: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    health_days_offline: Mapped[int | None] = mapped_column(
        Integer(), nullable=True
    )
    last_alert_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_alert_lag: Mapped[int | None] = mapped_column(Integer(), nullable=True)
