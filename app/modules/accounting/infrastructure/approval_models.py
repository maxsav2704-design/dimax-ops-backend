import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.infrastructure.db.base import Base, UUIDPrimaryKeyMixin, utcnow


class CommercialApprovalORM(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "commercial_approvals"
    mailbox_purpose = "commercial-contract-mailbox-v1"
    __table_args__ = (
        ForeignKeyConstraint(["company_id", "contract_id", "terms_id"],
            ["commercial_contract_terms.company_id", "commercial_contract_terms.contract_id", "commercial_contract_terms.id"],
            ondelete="RESTRICT", name="fk_commercial_approval_terms"),
        ForeignKeyConstraint(["company_id", "contract_id", "price_id"],
            ["commercial_price_versions.company_id", "commercial_price_versions.contract_id", "commercial_price_versions.id"],
            ondelete="RESTRICT", name="fk_commercial_approval_price"),
        ForeignKeyConstraint(["company_id", "factory_contact_id"],
            ["factory_contacts.company_id", "factory_contacts.id"], ondelete="RESTRICT", name="fk_commercial_approval_contact"),
        UniqueConstraint("company_id", "request_id", name="uq_commercial_approval_request"),
        CheckConstraint("expires_at > created_at", name="ck_commercial_approval_expiry"),
        CheckConstraint("mailbox_requests BETWEEN 0 AND 10 AND mailbox_attempts BETWEEN 0 AND 5", name="ck_commercial_approval_limits"),
        CheckConstraint("(mailbox_code_hash IS NULL AND mailbox_challenge_id IS NULL AND mailbox_code_expires_at IS NULL AND mailbox_requested_at IS NULL) OR (mailbox_code_hash IS NOT NULL AND mailbox_challenge_id IS NOT NULL AND mailbox_code_expires_at IS NOT NULL AND mailbox_requested_at IS NOT NULL AND mailbox_code_expires_at > mailbox_requested_at AND mailbox_requests > 0)", name="ck_commercial_approval_challenge"),
        CheckConstraint("(confirmed_at IS NULL AND confirmed_name IS NULL AND mailbox_verified_at IS NULL) OR (confirmed_at IS NOT NULL AND confirmed_name IS NOT NULL AND btrim(confirmed_name) <> '' AND mailbox_verified_at = confirmed_at AND mailbox_verified_at IS NOT NULL AND mailbox_code_hash IS NOT NULL AND confirmed_at < expires_at AND revoked_at IS NULL)", name="ck_commercial_approval_confirmation"),
        CheckConstraint("(revoked_at IS NULL AND revoked_by IS NULL AND revocation_reason IS NULL) OR (revoked_at IS NOT NULL AND revoked_by IS NOT NULL AND revocation_reason IS NOT NULL AND btrim(revocation_reason) <> '' AND confirmed_at IS NULL)", name="ck_commercial_approval_revocation"),
        Index("uq_commercial_approval_pending", "contract_id", unique=True,
              postgresql_where=text("revoked_at IS NULL AND confirmed_at IS NULL")),
        Index("uq_commercial_approval_confirmed", "terms_id", "price_id", unique=True,
              postgresql_where=text("confirmed_at IS NOT NULL")),
        Index("ix_commercial_approval_history", "company_id", "contract_id", "created_at"),
    )
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    contract_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    terms_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    price_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    factory_contact_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    factory_name: Mapped[str] = mapped_column(String(160), nullable=False)
    recipient_name: Mapped[str] = mapped_column(String(160), nullable=False)
    recipient_email: Mapped[str] = mapped_column(String(320), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    email_outbox_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("outbox_messages.id", ondelete="RESTRICT"), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"))
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
