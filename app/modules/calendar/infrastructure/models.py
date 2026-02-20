from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.infrastructure.db.base import (
    Base,
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    TenantMixin,
)
from app.modules.calendar.domain.enums import CalendarEventType


class CalendarEventORM(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin):
    __tablename__ = "calendar_events"
    __table_args__ = (
        CheckConstraint(
            "ends_at > starts_at", name="ck_calendar_event_time_range"
        ),
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    event_type: Mapped[CalendarEventType] = mapped_column(
        Enum(CalendarEventType, name="calendar_event_type"),
        nullable=False,
        index=True,
    )

    location: Mapped[str | None] = mapped_column(String(400), nullable=True)

    starts_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    ends_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )


class CalendarEventAssigneeORM(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin):
    __tablename__ = "calendar_event_assignees"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "event_id",
            "installer_id",
            name="uq_calendar_event_assignee",
        ),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("calendar_events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    installer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("installers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
