from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.infrastructure.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class CompanyPlanORM(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "company_plans"
    __table_args__ = (
        UniqueConstraint("company_id", name="uq_company_plans_company_id"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    plan_code: Mapped[str] = mapped_column(String(32), nullable=False, default="trial")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    max_users: Mapped[int | None] = mapped_column(nullable=True)
    max_admin_users: Mapped[int | None] = mapped_column(nullable=True)
    max_installer_users: Mapped[int | None] = mapped_column(nullable=True)
    max_installers: Mapped[int | None] = mapped_column(nullable=True)
    max_projects: Mapped[int | None] = mapped_column(nullable=True)
    max_doors_per_project: Mapped[int | None] = mapped_column(nullable=True)
    monthly_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
