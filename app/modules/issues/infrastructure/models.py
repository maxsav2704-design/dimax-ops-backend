from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.infrastructure.db.base import Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin
from app.modules.issues.domain.enums import IssuePriority, IssueStatus, IssueWorkflowState


class IssueORM(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin):
    __tablename__ = "issues"
    __table_args__ = (
        # 1 дверь = 1 активная проблема (в базовой версии)
        UniqueConstraint("company_id", "door_id", name="uq_issues_company_door"),
    )

    door_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("doors.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    status: Mapped[IssueStatus] = mapped_column(
        Enum(IssueStatus, name="issue_status"),
        nullable=False,
        default=IssueStatus.OPEN,
        index=True,
    )

    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    details: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    priority: Mapped[IssuePriority] = mapped_column(
        Enum(IssuePriority, name="issue_priority"),
        nullable=False,
        default=IssuePriority.P3,
        index=True,
    )
    workflow_state: Mapped[IssueWorkflowState] = mapped_column(
        Enum(IssueWorkflowState, name="issue_workflow_state"),
        nullable=False,
        default=IssueWorkflowState.NEW,
        index=True,
    )

    door: Mapped["DoorORM"] = relationship(back_populates="issue")
