from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Enum, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.addons.domain.enums import AddonFactSource
from app.shared.infrastructure.db.base import (
    Base,
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    TenantMixin,
)


class AddonTypeORM(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin):
    __tablename__ = "addon_types"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False, default="pcs")
    default_client_price: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0")
    )
    default_installer_price: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ProjectAddonPlanORM(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin):
    __tablename__ = "project_addon_plans"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    addon_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )

    qty_planned: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0")
    )
    client_price: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0")
    )
    installer_price: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0")
    )


class ProjectAddonFactORM(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin):
    __tablename__ = "project_addon_facts"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    addon_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    installer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )

    qty_done: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    done_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[AddonFactSource] = mapped_column(
        Enum(AddonFactSource, name="addon_fact_source"),
        nullable=False,
        default=AddonFactSource.ONLINE,
    )

    client_event_id: Mapped[str | None] = mapped_column(
        String(80), nullable=True
    )
