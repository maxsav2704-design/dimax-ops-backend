import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.infrastructure.db.base import Base, UUIDPrimaryKeyMixin, utcnow


class WorkPriceAccrualORM(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "work_price_accruals"
    __table_args__ = (
        UniqueConstraint("company_id", "request_id", name="uq_work_accrual_request"),
        UniqueConstraint("company_id", "approval_id", name="uq_work_accrual_approval"),
        UniqueConstraint("company_id", "sync_event_id", name="uq_work_accrual_event"),
        UniqueConstraint("company_id", "sync_queue_item_id", name="uq_work_accrual_queue"),
        UniqueConstraint("completed_work_id", name="uq_work_accrual_work"),
        ForeignKeyConstraint(["company_id", "approval_id"], ["work_price_approvals.company_id", "work_price_approvals.id"], ondelete="RESTRICT", name="fk_work_accrual_approval"),
        ForeignKeyConstraint(["company_id", "completed_work_id"], ["completed_work.company_id", "completed_work.id"], ondelete="RESTRICT", name="fk_work_accrual_work"),
        ForeignKeyConstraint(["company_id", "sync_event_id"], ["sync_events.company_id", "sync_events.id"], ondelete="RESTRICT", name="fk_work_accrual_event"),
        ForeignKeyConstraint(["company_id", "sync_queue_item_id"], ["sync_queue_items.company_id", "sync_queue_items.id"], ondelete="RESTRICT", name="fk_work_accrual_queue"),
        CheckConstraint("(sync_event_id IS NULL) <> (sync_queue_item_id IS NULL)", name="ck_work_accrual_source"),
        CheckConstraint("amount > 0 AND length(btrim(reason)) BETWEEN 10 AND 500", name="ck_work_accrual_values"),
        CheckConstraint("length(request_fingerprint) = 64 AND length(approval_hash) = 64", name="ck_work_accrual_hashes"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    approval_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    completed_work_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    sync_event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    sync_queue_item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    actor_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    approval_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    accrued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
