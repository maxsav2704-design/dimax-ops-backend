from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
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
    __table_args__ = (
        CheckConstraint(
            "default_client_price >= 0 AND default_installer_price >= 0",
            name="ck_addon_types_prices",
        ),
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
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
    __table_args__ = (
        CheckConstraint(
            "qty_planned >= 0 AND client_price >= 0 AND installer_price >= 0",
            name="ck_project_addon_plans_values",
        ),
        UniqueConstraint(
            "company_id",
            "project_id",
            "addon_type_id",
            name="uq_project_addon_plans_project_type",
        ),
    )

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
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class ProjectUrgencySurchargeORM(
    Base, UUIDPrimaryKeyMixin, TimestampMixin
):
    __tablename__ = "project_urgency_surcharges"
    __table_args__ = (
        CheckConstraint(
            "scope IN ('PROJECT', 'ORDER_NUMBER')",
            name="ck_project_urgency_surcharges_scope",
        ),
        CheckConstraint(
            "scope <> 'ORDER_NUMBER' OR order_number IS NOT NULL",
            name="ck_project_urgency_surcharges_order_scope",
        ),
        CheckConstraint(
            "client_amount >= 0 AND installer_amount >= 0",
            name="ck_project_urgency_surcharges_amounts",
        ),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    order_number: Mapped[str | None] = mapped_column(
        String(80), nullable=True, index=True
    )
    reason: Mapped[str] = mapped_column(String(200), nullable=False)
    client_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    installer_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    effective_date: Mapped[date | None] = mapped_column(Date(), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class ProjectAddonFactORM(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin):
    __tablename__ = "project_addon_facts"
    __table_args__ = (
        CheckConstraint(
            "qty_done > 0",
            name="ck_project_addon_facts_qty",
        ),
        UniqueConstraint(
            "company_id",
            "client_event_id",
            name="uq_project_addon_facts_client_event",
        ),
    )

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
