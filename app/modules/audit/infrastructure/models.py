from __future__ import annotations

import uuid
from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.infrastructure.db.base import Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin


class AuditLogORM(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin):
    __tablename__ = "audit_logs"

    actor_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)

    # что поменяли
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)     # "Door", "Project", "InstallerRate"
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False)          # "ADMIN_OVERRIDE", "UPDATE", "DELETE"
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    before: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
