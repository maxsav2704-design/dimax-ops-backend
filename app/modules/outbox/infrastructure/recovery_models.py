from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.infrastructure.db.base import Base, UUIDPrimaryKeyMixin


class OutboxRecoveryORM(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "outbox_recoveries"
    __table_args__ = (
        UniqueConstraint("company_id", "epoch", name="uq_outbox_recovery_epoch"),
        UniqueConstraint("company_id", "id", name="uq_outbox_recovery_tenant"),
        CheckConstraint("btrim(reason) <> ''", name="ck_outbox_recovery_reason"),
    )
    company_id: Mapped[UUID] = mapped_column(ForeignKey("companies.id"), nullable=False)
    epoch: Mapped[UUID] = mapped_column(nullable=False)
    opened_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reason: Mapped[str] = mapped_column(String(1000))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    released_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))


class OutboxRecoveryItemORM(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "outbox_recovery_items"
    __table_args__ = (
        ForeignKeyConstraint(["company_id", "recovery_id"], ["outbox_recoveries.company_id", "outbox_recoveries.id"]),
        ForeignKeyConstraint(["company_id", "outbox_id"], ["outbox_messages.company_id", "outbox_messages.id"]),
        UniqueConstraint("recovery_id", "outbox_id", name="uq_outbox_recovery_item"),
        UniqueConstraint("company_id", "id", name="uq_outbox_recovery_item_tenant"),
        CheckConstraint("action IS NULL OR action IN ('HOLD', 'RETRY', 'ACCEPTED')", name="ck_outbox_recovery_action"),
        CheckConstraint("revision >= 0", name="ck_outbox_recovery_revision"),
    )
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    recovery_id: Mapped[UUID] = mapped_column(nullable=False)
    outbox_id: Mapped[UUID] = mapped_column(nullable=False)
    payload_digest: Mapped[str] = mapped_column(String(64))
    action: Mapped[str | None] = mapped_column(String(16))
    revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class OutboxRecoveryDecisionORM(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "outbox_recovery_decisions"
    __table_args__ = (
        ForeignKeyConstraint(["company_id", "item_id"], ["outbox_recovery_items.company_id", "outbox_recovery_items.id"]),
        UniqueConstraint("company_id", "request_id", name="uq_outbox_recovery_request"),
        UniqueConstraint("item_id", "revision", name="uq_outbox_recovery_decision_revision"),
        CheckConstraint("action IN ('HOLD', 'RETRY', 'ACCEPTED') AND revision > 0", name="ck_outbox_recovery_decision"),
        CheckConstraint("btrim(reason) <> '' AND btrim(evidence) <> ''", name="ck_outbox_recovery_evidence"),
        CheckConstraint("(action = 'ACCEPTED') = (accepted_at IS NOT NULL)", name="ck_outbox_recovery_accepted"),
    )
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    item_id: Mapped[UUID] = mapped_column(nullable=False)
    request_id: Mapped[UUID] = mapped_column(nullable=False)
    revision: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(String(1000))
    evidence: Mapped[str] = mapped_column(String(1000))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
