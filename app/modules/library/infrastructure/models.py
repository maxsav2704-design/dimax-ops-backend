from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.infrastructure.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ProductLibraryItemORM(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "product_library_items"
    __table_args__ = (
        UniqueConstraint("company_id", "sku", name="uq_product_library_company_sku"),
        CheckConstraint(
            "status IN ('ACTIVE', 'ARCHIVED')",
            name="ck_product_library_status",
        ),
        CheckConstraint(
            "unit IN ('piece', 'set', 'point')",
            name="ck_product_library_unit",
        ),
        Index("ix_product_library_company_status", "company_id", "status"),
        Index("ix_product_library_install_type", "company_id", "install_type"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sku: Mapped[str] = mapped_column(String(80), nullable=False)
    name_ru: Mapped[str] = mapped_column(String(200), nullable=False)
    name_he: Mapped[str] = mapped_column(String(200), nullable=False)
    install_type: Mapped[str] = mapped_column(String(120), nullable=False)
    manufacturer: Mapped[str | None] = mapped_column(String(200), nullable=True)
    unit: Mapped[str] = mapped_column(String(20), nullable=False, default="piece")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
