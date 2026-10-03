from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, String, UniqueConstraint, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.infrastructure.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class FactoryPriceActivationORM(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "factory_price_activations"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_factory_activation_tenant_id"),
        ForeignKeyConstraint(
            ["company_id", "price_list_id"], ["factory_price_lists.company_id", "factory_price_lists.id"],
            ondelete="RESTRICT", name="fk_factory_activation_tenant_list",
        ),
        ForeignKeyConstraint(
            ["company_id", "price_list_id", "approval_id"],
            ["factory_price_approvals.company_id", "factory_price_approvals.price_list_id", "factory_price_approvals.id"],
            ondelete="RESTRICT", name="fk_factory_activation_tenant_approval",
        ),
        UniqueConstraint("company_id", "price_list_id", name="uq_factory_activation_list"),
        UniqueConstraint("company_id", "effective_from", name="uq_factory_activation_time"),
        UniqueConstraint("company_id", "request_id", name="uq_factory_activation_request"),
        CheckConstraint("btrim(reason) <> ''", name="ck_factory_activation_reason"),
        CheckConstraint("effective_from = created_at", name="ck_factory_activation_time"),
        CheckConstraint("length(snapshot_hash) = 64 AND length(request_fingerprint) = 64", name="ck_factory_activation_hashes"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    price_list_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    approval_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
