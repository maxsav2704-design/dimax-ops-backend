from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.infrastructure.db.base import Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin


class InstallerRateORM(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin):
    __tablename__ = "installer_rates"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "installer_id",
            "door_type_id",
            "effective_from",
            name="uq_rates_installer_door_type_from",
        ),
        CheckConstraint("price >= 0", name="ck_rates_price_nonnegative"),
        Index(
            "ix_rates_scope_effective_from",
            "company_id",
            "installer_id",
            "door_type_id",
            "effective_from",
        ),
    )

    installer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("installers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    door_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("door_types.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # ILS
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
