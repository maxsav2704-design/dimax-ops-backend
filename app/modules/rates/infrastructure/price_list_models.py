from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Integer,
    Numeric, String, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.infrastructure.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class FactoryPriceListORM(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "factory_price_lists"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_factory_price_lists_tenant_id"),
        UniqueConstraint("company_id", "version", name="uq_factory_price_lists_version"),
        UniqueConstraint("company_id", "request_id", name="uq_factory_price_lists_request"),
        CheckConstraint("version > 0", name="ck_factory_price_lists_version"),
        CheckConstraint("currency = 'ILS'", name="ck_factory_price_lists_currency"),
        CheckConstraint("btrim(reason) <> '' AND btrim(agreement_reference) <> ''",
                        name="ck_factory_price_lists_reference"),
        CheckConstraint(
            "(status IN ('DRAFT', 'CONFIRMED') AND cancelled_at IS NULL AND cancelled_by IS NULL "
            "AND cancellation_reason IS NULL) OR "
            "(status = 'CANCELLED' AND cancelled_at IS NOT NULL AND cancelled_by IS NOT NULL "
            "AND cancellation_reason IS NOT NULL AND btrim(cancellation_reason) <> '')",
            name="ck_factory_price_lists_status",
        ),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="ILS")
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    agreement_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False,
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"),
    )
    cancellation_reason: Mapped[str | None] = mapped_column(String(1000))


class FactoryPriceListItemORM(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "factory_price_list_items"
    __table_args__ = (
        UniqueConstraint("company_id", "price_list_id", "id", name="uq_factory_price_items_tenant_list_id"),
        ForeignKeyConstraint(
            ["company_id", "price_list_id"], ["factory_price_lists.company_id", "factory_price_lists.id"],
            ondelete="CASCADE", name="fk_factory_price_items_tenant_list",
        ),
        UniqueConstraint("price_list_id", "door_type_id", name="uq_factory_price_items_door"),
        UniqueConstraint("price_list_id", "addon_type_id", name="uq_factory_price_items_addon"),
        CheckConstraint(
            "(kind = 'DOOR' AND door_type_id IS NOT NULL AND addon_type_id IS NULL) OR "
            "(kind = 'ADDON' AND addon_type_id IS NOT NULL AND door_type_id IS NULL)",
            name="ck_factory_price_items_target",
        ),
        CheckConstraint("installer_price > 0 AND installer_price < 10000000000",
                        name="ck_factory_price_items_price"),
        CheckConstraint("btrim(name) <> '' AND btrim(unit) <> ''", name="ck_factory_price_items_label"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    price_list_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    door_type_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("door_types.id", ondelete="RESTRICT"),
    )
    addon_type_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("addon_types.id", ondelete="RESTRICT"),
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    installer_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
