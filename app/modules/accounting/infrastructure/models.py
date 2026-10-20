from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import (
    Boolean, CheckConstraint, Date, ForeignKey, ForeignKeyConstraint,
    Integer, Numeric, String, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.infrastructure.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class CommercialContractORM(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "commercial_contracts"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_commercial_contract_tenant"),
        UniqueConstraint("company_id", "reference", name="uq_commercial_contract_reference"),
        UniqueConstraint("company_id", "request_id", name="uq_commercial_contract_request"),
        CheckConstraint("status = 'DRAFT' AND currency = 'ILS'", name="ck_commercial_contract_draft"),
        CheckConstraint(
            "btrim(factory_name) <> '' AND btrim(reference) <> '' AND btrim(reason) <> ''",
            name="ck_commercial_contract_labels",
        ),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False,
    )
    factory_name: Mapped[str] = mapped_column(String(200), nullable=False)
    reference: Mapped[str] = mapped_column(String(200), nullable=False)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="ILS")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="DRAFT")
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False)
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False,
    )


class CommercialPriceVersionORM(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "commercial_price_versions"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_commercial_price_tenant"),
        ForeignKeyConstraint(
            ["company_id", "contract_id"], ["commercial_contracts.company_id", "commercial_contracts.id"],
            ondelete="RESTRICT", name="fk_commercial_price_contract",
        ),
        UniqueConstraint("company_id", "contract_id", "version", name="uq_commercial_price_version"),
        UniqueConstraint("company_id", "request_id", name="uq_commercial_price_request"),
        CheckConstraint("version > 0 AND status = 'DRAFT'", name="ck_commercial_price_draft"),
        CheckConstraint(
            "btrim(reason) <> '' AND btrim(agreement_reference) <> ''",
            name="ck_commercial_price_labels",
        ),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    contract_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="DRAFT")
    proposed_from: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    agreement_reference: Mapped[str] = mapped_column(String(200), nullable=False)
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False,
    )


class CommercialPriceItemORM(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "commercial_price_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "price_version_id"],
            ["commercial_price_versions.company_id", "commercial_price_versions.id"],
            ondelete="RESTRICT", name="fk_commercial_item_version",
        ),
        UniqueConstraint("price_version_id", "kind", "door_type_id", "stage_code",
                         name="uq_commercial_item_door_stage"),
        UniqueConstraint("price_version_id", "addon_type_id", name="uq_commercial_item_addon"),
        CheckConstraint(
            "(kind = 'INSTALLATION' AND door_type_id IS NOT NULL AND addon_type_id IS NULL AND stage_code = '') OR "
            "(kind = 'STAGE' AND door_type_id IS NOT NULL AND addon_type_id IS NULL "
            "AND stage_code ~ '^[A-Z][A-Z0-9_]{0,39}$') OR "
            "(kind = 'ADDON' AND door_type_id IS NULL AND addon_type_id IS NOT NULL AND stage_code = '')",
            name="ck_commercial_item_target",
        ),
        CheckConstraint("unit_price_ex_vat >= 0 AND unit_price_ex_vat < 10000000000",
                        name="ck_commercial_item_price"),
        CheckConstraint("btrim(name) <> '' AND btrim(unit) <> ''", name="ck_commercial_item_labels"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    price_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    door_type_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("door_types.id", ondelete="RESTRICT"),
    )
    addon_type_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("addon_types.id", ondelete="RESTRICT"),
    )
    stage_code: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    unit_price_ex_vat: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
