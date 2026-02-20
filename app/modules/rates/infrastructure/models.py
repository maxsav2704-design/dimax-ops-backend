from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.infrastructure.db.base import Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin


class InstallerRateORM(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin):
    __tablename__ = "installer_rates"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "installer_id", "door_type_id", name="uq_rates_installer_door_type"
        ),
        CheckConstraint("price >= 0", name="ck_rates_price_nonnegative"),
    )

    installer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("installers.id"), nullable=False, index=True
    )
    door_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("door_types.id"), nullable=False, index=True
    )

    # ILS
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
