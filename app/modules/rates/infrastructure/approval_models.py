from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.infrastructure.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class FactoryPriceApprovalORM(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "factory_price_approvals"
    __table_args__ = (
        UniqueConstraint("company_id", "price_list_id", "id", name="uq_factory_approvals_tenant_list_id"),
        ForeignKeyConstraint(
            ["company_id", "price_list_id"], ["factory_price_lists.company_id", "factory_price_lists.id"],
            ondelete="CASCADE", name="fk_factory_approvals_tenant_list",
        ),
        CheckConstraint("expires_at > created_at", name="ck_factory_approvals_expiry"),
        CheckConstraint("mailbox_requests BETWEEN 0 AND 10 AND mailbox_attempts BETWEEN 0 AND 5",
                        name="ck_factory_approvals_mailbox_limits"),
        CheckConstraint(
            "(mailbox_code_hash IS NULL AND mailbox_challenge_id IS NULL AND mailbox_code_expires_at IS NULL "
            "AND mailbox_requested_at IS NULL) OR (mailbox_code_hash IS NOT NULL AND mailbox_challenge_id IS NOT NULL "
            "AND mailbox_code_expires_at IS NOT NULL AND mailbox_requested_at IS NOT NULL "
            "AND mailbox_code_expires_at > mailbox_requested_at AND mailbox_requests > 0)",
            name="ck_factory_approvals_mailbox_challenge"),
        CheckConstraint("mailbox_verified_at IS NULL OR (confirmed_at IS NOT NULL "
                        "AND mailbox_code_hash IS NOT NULL AND mailbox_verified_at = confirmed_at)",
                        name="ck_factory_approvals_mailbox_verified"),
        CheckConstraint(
            "btrim(factory_name) <> '' AND btrim(recipient_name) <> '' AND btrim(recipient_email) <> ''",
            name="ck_factory_approvals_recipient",
        ),
        CheckConstraint(
            "(revoked_at IS NULL AND revoked_by IS NULL AND revocation_reason IS NULL) OR "
            "(revoked_at IS NOT NULL AND revoked_by IS NOT NULL AND revocation_reason IS NOT NULL "
            "AND btrim(revocation_reason) <> '' AND confirmed_at IS NULL)",
            name="ck_factory_approvals_revocation",
        ),
        CheckConstraint(
            "(confirmed_at IS NULL AND confirmed_name IS NULL) OR "
            "(confirmed_at IS NOT NULL AND confirmed_name IS NOT NULL AND btrim(confirmed_name) <> '' "
            "AND confirmed_at < expires_at AND revoked_at IS NULL)",
            name="ck_factory_approvals_confirmation",
        ),
        Index("uq_factory_approvals_pending", "price_list_id", unique=True,
              postgresql_where=text("revoked_at IS NULL AND confirmed_at IS NULL")),
        Index("uq_factory_approvals_confirmed", "price_list_id", unique=True,
              postgresql_where=text("confirmed_at IS NOT NULL")),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    price_list_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    factory_name: Mapped[str] = mapped_column(String(160), nullable=False)
    recipient_name: Mapped[str] = mapped_column(String(160), nullable=False)
    recipient_email: Mapped[str] = mapped_column(String(320), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"),
    )
    revocation_reason: Mapped[str | None] = mapped_column(String(1000))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_name: Mapped[str | None] = mapped_column(String(160))
    mailbox_challenge_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    mailbox_code_hash: Mapped[str | None] = mapped_column(String(64))
    mailbox_code_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mailbox_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mailbox_requests: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    mailbox_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    mailbox_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
