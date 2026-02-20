from __future__ import annotations

import uuid
from sqlalchemy import Boolean, String, UniqueConstraint
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
