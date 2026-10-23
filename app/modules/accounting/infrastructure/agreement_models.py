import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, ForeignKeyConstraint, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.infrastructure.db.base import Base, UUIDPrimaryKeyMixin, utcnow


class CommercialAgreementORM(Base, UUIDPrimaryKeyMixin):
    """A factory-confirmed pair of versions put into effect by an OWNER from a date (0087).

    Gap-free per contract, one row per factory decision, closed only by the next agreement.
    Being in effect is not a claim, an invoice or a payment.
    """

    __tablename__ = "commercial_agreements"
    __table_args__ = (
        ForeignKeyConstraint(["company_id", "contract_id", "terms_id"],
            ["commercial_contract_terms.company_id", "commercial_contract_terms.contract_id", "commercial_contract_terms.id"],
            ondelete="RESTRICT", name="fk_commercial_agreement_terms"),
        ForeignKeyConstraint(["company_id", "contract_id", "price_id"],
            ["commercial_price_versions.company_id", "commercial_price_versions.contract_id", "commercial_price_versions.id"],
            ondelete="RESTRICT", name="fk_commercial_agreement_price"),
        ForeignKeyConstraint(["company_id", "contract_id", "approval_id"],
            ["commercial_approvals.company_id", "commercial_approvals.contract_id", "commercial_approvals.id"],
            ondelete="RESTRICT", name="fk_commercial_agreement_approval"),
        UniqueConstraint("company_id", "request_id", name="uq_commercial_agreement_request"),
        UniqueConstraint("approval_id", name="uq_commercial_agreement_approval"),
        CheckConstraint("effective_until IS NULL OR effective_until >= effective_from", name="ck_commercial_agreement_dates"),
        CheckConstraint("effective_from >= DATE '2026-11-10'", name="ck_commercial_agreement_cutover"),
        CheckConstraint("btrim(reason) <> '' AND btrim(activated_by_name) <> ''", name="ck_commercial_agreement_labels"),
        Index("uq_commercial_agreement_open", "contract_id", unique=True, postgresql_where=text("effective_until IS NULL")),
        Index("ix_commercial_agreement_lookup", "company_id", "contract_id", "effective_from"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    contract_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    terms_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    price_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    approval_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_until: Mapped[date | None] = mapped_column(Date)
    activated_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    activated_by_name: Mapped[str] = mapped_column(String(255), nullable=False)
    activated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
