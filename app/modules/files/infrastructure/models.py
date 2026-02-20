from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.infrastructure.db.base import (
    Base,
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    TenantMixin,
)


class FileDownloadTokenORM(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin):
    __tablename__ = "file_download_tokens"

    token: Mapped[str] = mapped_column(
        String(120), nullable=False, unique=True, index=True
    )

    object_key: Mapped[str] = mapped_column(String(800), nullable=False)
    bucket: Mapped[str] = mapped_column(String(100), nullable=False)

    mime_type: Mapped[str] = mapped_column(
        String(100), nullable=False, default="application/octet-stream"
    )
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    uses_left: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_used_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_used_ua: Mapped[str | None] = mapped_column(Text, nullable=True)

    audience: Mapped[str | None] = mapped_column(String(120), nullable=True)


class FileDownloadEventORM(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin):
    __tablename__ = "file_download_events"

    source: Mapped[str] = mapped_column(String(30), nullable=False)
    token: Mapped[str | None] = mapped_column(String(120), nullable=True)

    object_key: Mapped[str] = mapped_column(String(800), nullable=False)
    bucket: Mapped[str] = mapped_column(String(100), nullable=False)

    mime_type: Mapped[str] = mapped_column(
        String(100), nullable=False, default="application/octet-stream"
    )
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
