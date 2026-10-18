from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.infrastructure.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

# System risks live on the project, not on a door (migration 0078). A door holds
# at most one real issue reported by people; sync / delivery risks are detected
# by the system and must never take that slot or reach the installer's device.
RISK_SYNC = "SYNC"
RISK_DELIVERY_OUTBOX = "DELIVERY_OUTBOX"
RISK_KINDS = (RISK_SYNC, RISK_DELIVERY_OUTBOX)


class ProjectRiskORM(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "project_risks"
    __table_args__ = (
        UniqueConstraint("company_id", "project_id", "kind", name="uq_project_risks_scope_kind"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="OPEN")
    details: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
