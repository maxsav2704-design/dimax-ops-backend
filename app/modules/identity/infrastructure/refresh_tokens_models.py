from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.infrastructure.db.base import (
    Base,
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    TenantMixin,
)


class RefreshTokenORM(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin):
    """
    Храним ХЕШ refresh token (или его jti) + lifecycle.
    Это даёт:
    - rotation (старый становится revoked)
    - возможность "logout all" / revoke
    """
    __tablename__ = "auth_refresh_tokens"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "jti", name="uq_auth_refresh_tokens_company_jti"
        ),
        Index("ix_auth_refresh_tokens_user", "company_id", "user_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    jti: Mapped[str] = mapped_column(String(64), nullable=False)  # UUID string
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    replaced_by_jti: Mapped[str | None] = mapped_column(String(64), nullable=True)
