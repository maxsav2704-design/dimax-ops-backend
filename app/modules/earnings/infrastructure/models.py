from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.infrastructure.db.base import Base, UUIDPrimaryKeyMixin, TimestampMixin, utcnow


class CompletedWorkORM(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "completed_work"
    __table_args__ = (
        CheckConstraint(
            "entry_type IN ('ORIGINAL', 'REVERSAL', 'CORRECTION')",
            name="ck_completed_work_entry_type",
        ),
        CheckConstraint(
            "work_kind IN ('DOOR', 'ADDON')",
            name="ck_completed_work_work_kind",
        ),
        CheckConstraint(
            "quantity > 0",
            name="ck_completed_work_quantity_positive",
        ),
        CheckConstraint(
            "(entry_type = 'ORIGINAL' AND correction_ref_id IS NULL) OR "
            "(entry_type IN ('REVERSAL', 'CORRECTION') AND correction_ref_id IS NOT NULL)",
            name="ck_completed_work_correction_ref",
        ),
        CheckConstraint(
            "(entry_type = 'REVERSAL' AND rate_snapshot < 0 AND amount_snapshot < 0) OR "
            "(entry_type IN ('ORIGINAL', 'CORRECTION') AND rate_snapshot > 0 AND amount_snapshot > 0)",
            name="ck_completed_work_amount_sign",
        ),
        CheckConstraint(
            "(work_kind = 'DOOR' AND door_id IS NOT NULL AND addon_fact_id IS NULL) OR "
            "(work_kind = 'ADDON' AND door_id IS NULL AND addon_fact_id IS NOT NULL)",
            name="ck_completed_work_subject",
        ),
        Index("ix_completed_work_company_completed_at", "company_id", "completed_at", "id"),
        Index("ix_completed_work_company_project_completed_at", "company_id", "project_id", "completed_at", "id"),
        Index("ix_completed_work_installer_completed_at", "installer_id", "completed_at"),
        Index(
            "uq_completed_work_addon_fact_original",
            "addon_fact_id",
            unique=True,
            postgresql_where=text(
                "addon_fact_id IS NOT NULL AND entry_type = 'ORIGINAL'"
            ),
        ),
        Index(
            "uq_completed_work_correction_ref_entry_type",
            "correction_ref_id",
            "entry_type",
            unique=True,
            postgresql_where=text("correction_ref_id IS NOT NULL"),
        ),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
    )
    door_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("doors.id", ondelete="SET NULL"),
        nullable=True,
    )
    addon_fact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("project_addon_facts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    installer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("installers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("1.00"))
    rate_snapshot: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    amount_snapshot: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    work_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="DOOR")
    entry_type: Mapped[str] = mapped_column(String(20), nullable=False, default="ORIGINAL")
    correction_ref_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("completed_work.id", ondelete="SET NULL"),
        nullable=True,
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class ClientPriceSnapshotORM(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "client_price_snapshots"
    __table_args__ = (
        CheckConstraint(
            "base_client_rate >= 0 AND final_client_rate >= 0 AND final_installer_rate > 0",
            name="ck_client_price_snapshots_rates",
        ),
        UniqueConstraint(
            "completed_work_id",
            name="uq_client_price_snapshots_completed_work_id",
        ),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    completed_work_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("completed_work.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    base_client_rate: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    final_client_rate: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    final_installer_rate: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
