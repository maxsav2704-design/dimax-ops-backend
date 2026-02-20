from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.infrastructure.db.base import (
    Base,
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    TenantMixin,
)
from app.modules.journal.domain.enums import (
    JournalDeliveryStatus,
    JournalStatus,
)


class JournalORM(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin):
    __tablename__ = "journals"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "public_token", name="uq_journals_company_public_token"
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    status: Mapped[JournalStatus] = mapped_column(
        Enum(JournalStatus, name="journal_status"),
        nullable=False,
        default=JournalStatus.DRAFT,
        index=True,
    )

    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    public_token: Mapped[str | None] = mapped_column(
        String(80), nullable=True, index=True
    )
    public_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    lock_header: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    lock_table: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    lock_footer: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    signed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    signer_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    snapshot_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    email_delivery_status: Mapped[JournalDeliveryStatus] = mapped_column(
        Enum(JournalDeliveryStatus, name="journal_delivery_status"),
        nullable=False,
        default=JournalDeliveryStatus.NONE,
        index=True,
    )
    whatsapp_delivery_status: Mapped[JournalDeliveryStatus] = mapped_column(
        Enum(JournalDeliveryStatus, name="journal_delivery_status"),
        nullable=False,
        default=JournalDeliveryStatus.NONE,
        index=True,
    )

    email_last_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    whatsapp_last_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    whatsapp_delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    email_last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    whatsapp_last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class JournalDoorItemORM(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin):
    """
    Снапшот строки журнала (двери) на момент refresh/create.
    """
    __tablename__ = "journal_door_items"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "journal_id",
            "door_id",
            name="uq_journal_door_items_unique",
        ),
    )

    journal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("journals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    door_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doors.id"), nullable=False, index=True
    )

    unit_label: Mapped[str] = mapped_column(String(120), nullable=False)
    door_type_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    installed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    extra: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class JournalSignatureORM(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin):
    __tablename__ = "journal_signatures"

    journal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("journals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    signer_name: Mapped[str] = mapped_column(String(200), nullable=False)
    signature_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)


class JournalFileORM(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin):
    __tablename__ = "journal_files"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "journal_id", "kind", name="uq_journal_files_one_kind"
        ),
    )

    journal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("journals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str] = mapped_column(
        String(100), nullable=False, default="application/pdf"
    )
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    storage_provider: Mapped[str] = mapped_column(
        String(30), nullable=False, default="MINIO"
    )
    bucket: Mapped[str] = mapped_column(
        String(100), nullable=False, default="dimax"
    )
