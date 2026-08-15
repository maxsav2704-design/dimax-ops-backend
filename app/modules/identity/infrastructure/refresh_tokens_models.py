from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.infrastructure.db.base import (
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    utcnow,
)


class RefreshTokenORM(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Храним ХЕШ refresh token (или его jti) + lifecycle.
    Это даёт:
    - rotation (старый становится revoked)
    - возможность "logout all" / revoke
    """
    __tablename__ = "refresh_sessions"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "jti", name="uq_refresh_sessions_company_jti"
        ),
        Index("ix_refresh_sessions_user", "company_id", "user_id"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    jti: Mapped[str] = mapped_column(String(64), nullable=False)  # UUID string
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    device_id: Mapped[str] = mapped_column(String, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ip_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoke_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)

    replaced_by_jti: Mapped[str | None] = mapped_column(String(64), nullable=True)
