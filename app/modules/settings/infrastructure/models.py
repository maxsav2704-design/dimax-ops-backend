from __future__ import annotations

from sqlalchemy import Boolean, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.infrastructure.db.base import (
    Base,
    TenantMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class CommunicationTemplateORM(
    Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin
):
    __tablename__ = "communication_templates"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "code",
            name="uq_communication_templates_company_code",
        ),
    )

    code: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    subject: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    send_email: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    send_whatsapp: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
