from __future__ import annotations

import uuid
from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.infrastructure.db.base import (
    Base,
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    TenantMixin,
    SoftDeleteMixin,
)


class InstallerORM(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, SoftDeleteMixin):
    __tablename__ = "installers"
    __table_args__ = (
        UniqueConstraint("company_id", "phone", name="uq_installers_company_phone"),
    )

    full_name: Mapped[str] = mapped_column(String(255), nullable=False)

    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    passport_id: Mapped[str | None] = mapped_column(String(80), nullable=True)

    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")  # ACTIVE/BUSY/INACTIVE
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # если монтажник привязан к конкретному user (вход в мобилку)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)


class InstallerProfileORM(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin):
    """Mobile installer profile: display name and preferred language."""

    __tablename__ = "installer_profiles"
    __table_args__ = (
        UniqueConstraint("company_id", "user_id", name="uq_installer_profiles_company_user"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    language: Mapped[str] = mapped_column(String(8), nullable=False, default="en")
