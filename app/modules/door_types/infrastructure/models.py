from __future__ import annotations

from sqlalchemy import Boolean, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.infrastructure.db.base import (
    Base,
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    TenantMixin,
    SoftDeleteMixin,
    SlugCodeMixin,
)


class DoorTypeORM(
    Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, SoftDeleteMixin, SlugCodeMixin
):
    __tablename__ = "door_types"
    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_door_types_company_code"),
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
