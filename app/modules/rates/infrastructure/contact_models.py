from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.infrastructure.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class FactoryContactORM(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "factory_contacts"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_factory_contacts_tenant_id"),
        CheckConstraint("btrim(factory_name) <> '' AND btrim(recipient_name) <> '' AND btrim(recipient_email) <> '' "
                        "AND btrim(authority_reference) <> ''", name="ck_factory_contacts_identity"),
        CheckConstraint("(revoked_at IS NULL AND revoked_by IS NULL) OR "
                        "(revoked_at IS NOT NULL AND revoked_by IS NOT NULL)", name="ck_factory_contacts_revocation"),
        Index("uq_factory_contacts_current", "company_id", unique=True,
              postgresql_where=text("revoked_at IS NULL")),
    )

    company_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"))
    factory_name: Mapped[str] = mapped_column(String(160))
    recipient_name: Mapped[str] = mapped_column(String(160))
    recipient_email: Mapped[str] = mapped_column(String(320))
    authority_reference: Mapped[str] = mapped_column(String(500))
    approved_by: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
