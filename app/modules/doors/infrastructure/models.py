from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.infrastructure.db.base import (
    Base,
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    TenantMixin,
)
from app.modules.doors.domain.enums import DoorStatus


class DoorORM(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin):
    __tablename__ = "doors"
    __table_args__ = (
        # чтобы в одном проекте не было дублей по квартире/позиции/типу
        UniqueConstraint(
            "company_id", "project_id", "unit_label", "door_type_id",
            name="uq_doors_project_unit_type",
        ),
        CheckConstraint("our_price >= 0", name="ck_doors_our_price_nonnegative"),
        Index("ix_doors_project_status", "project_id", "status"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    door_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("door_types.id"),
        nullable=False,
        index=True,
    )

    # "квартира/номер" — универсальная метка (apt 12, stair A-3, storage 7 и т.д.)
    unit_label: Mapped[str] = mapped_column(String(120), nullable=False)
    order_number: Mapped[str | None] = mapped_column(String(80), nullable=True)
    house_number: Mapped[str | None] = mapped_column(String(40), nullable=True)
    floor_label: Mapped[str | None] = mapped_column(String(40), nullable=True)
    apartment_number: Mapped[str | None] = mapped_column(String(40), nullable=True)
    location_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    door_marking: Mapped[str | None] = mapped_column(String(120), nullable=True)

    our_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    installer_rate_snapshot: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )

    status: Mapped[DoorStatus] = mapped_column(
        Enum(DoorStatus, name="door_status"),
        nullable=False,
        default=DoorStatus.NOT_INSTALLED,
        index=True,
    )

    installer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("installers.id"),
        nullable=True,
        index=True,
    )

    # причина только если NOT_INSTALLED
    reason_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("reasons.id"),
        nullable=True,
        index=True,
    )

    comment: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    installed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # "замок" на уровне домена: как только INSTALLED → true (и дальше только admin override)
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Связи
    project: Mapped["ProjectORM"] = relationship(back_populates="doors")
    issue: Mapped["IssueORM | None"] = relationship(
        back_populates="door",
        uselist=False,
        cascade="all,delete-orphan",
    )
