from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.infrastructure.db.base import Base, utcnow


class FactoryEarningPriceORM(Base):
    __tablename__ = "factory_earning_prices"
    __table_args__ = (
        ForeignKeyConstraint(["company_id", "completed_work_id"], ["completed_work.company_id", "completed_work.id"],
                             ondelete="RESTRICT", name="fk_factory_earning_work"),
        ForeignKeyConstraint(["company_id", "price_list_id", "price_list_item_id"],
            ["factory_price_list_items.company_id", "factory_price_list_items.price_list_id", "factory_price_list_items.id"],
            ondelete="RESTRICT", name="fk_factory_earning_item"),
        ForeignKeyConstraint(["company_id", "price_list_id", "approval_id"],
            ["factory_price_approvals.company_id", "factory_price_approvals.price_list_id", "factory_price_approvals.id"],
            ondelete="RESTRICT", name="fk_factory_earning_approval"),
        ForeignKeyConstraint(["company_id", "activation_id"],
            ["factory_price_activations.company_id", "factory_price_activations.id"],
            ondelete="RESTRICT", name="fk_factory_earning_activation"),
        CheckConstraint("selection IN ('AT_EXECUTION', 'FIRST_CONFIRMED_LEGACY')", name="ck_factory_earning_selection"),
        CheckConstraint("confirmed_rate > 0 AND confirmed_rate < 10000000000", name="ck_factory_earning_rate"),
        CheckConstraint("version > 0 AND currency = 'ILS' AND btrim(unit) <> '' AND length(snapshot_hash) = 64",
                        name="ck_factory_earning_snapshot"),
    )

    completed_work_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    price_list_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    price_list_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    approval_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    activation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    selection: Mapped[str] = mapped_column(String(32), nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    confirmed_rate: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    performed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
