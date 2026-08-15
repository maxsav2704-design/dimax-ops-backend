from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Sequence,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.sync.domain.enums import SyncChangeType, SyncEventType
from app.shared.infrastructure.db.base import (
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class SyncEventORM(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "sync_events"
    __table_args__ = (
        Index("ix_sync_events_company_project", "company_id", "project_id"),
        Index("ix_sync_events_company_installer", "company_id", "installer_id"),
        Index("ix_sync_events_created_at", "created_at"),
        UniqueConstraint(
            "company_id",
            "client_event_id",
            name="uq_sync_events_client_event",
        ),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    installer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
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


class SyncChangeLogORM(Base):
    __tablename__ = "sync_change_log"
    __table_args__ = (
        Index("ix_sync_change_company_cursor", "company_id", "cursor_id"),
        Index(
            "ix_sync_change_company_installer_cursor",
            "company_id",
            "installer_id",
            "cursor_id",
        ),
        Index("ix_sync_change_project", "company_id", "project_id"),
    )

    cursor_id: Mapped[int | None] = mapped_column(
        BigInteger,
        primary_key=True,
        nullable=False,
        server_default=Sequence("sync_cursor_seq").next_value(),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

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


class InstallerSyncStateORM(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "installer_sync_state"
    __table_args__ = (
        Index("ix_installer_sync_state_company", "company_id"),
        UniqueConstraint(
            "company_id",
            "installer_id",
            name="uq_installer_sync_state_company_installer",
        ),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
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


class SyncQueueItemORM(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "sync_queue_items"
    __table_args__ = (
        Index("ix_sync_queue_items_user_status", "user_id", "status"),
        Index("ix_sync_queue_items_company_project", "company_id", "project_id"),
        CheckConstraint(
            "status IN ('PENDING', 'APPLIED', 'CONFLICT', 'BLOCKED', 'AUTH_REQUIRED')",
            name="ck_sync_queue_items_status",
        ),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    device_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    operation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    base_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    conflict_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
