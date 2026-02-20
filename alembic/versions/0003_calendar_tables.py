"""calendar tables

Revision ID: 0003_calendar
Revises: 0002_journal
Create Date: 2026-02-13
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_calendar"
down_revision = "0002_journal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    event_type = postgresql.ENUM(
        "installation",
        "delivery",
        "meeting",
        "consultation",
        "inspection",
        name="calendar_event_type",
        create_type=False,
    )
    event_type.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "calendar_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("event_type", event_type, nullable=False),
        sa.Column("location", sa.String(length=400), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint("ends_at > starts_at", name="ck_calendar_event_time_range"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_calendar_events_company_id", "calendar_events", ["company_id"])
    op.create_index("ix_calendar_events_starts_at", "calendar_events", ["starts_at"])
    op.create_index("ix_calendar_events_ends_at", "calendar_events", ["ends_at"])
    op.create_index("ix_calendar_events_event_type", "calendar_events", ["event_type"])
    op.create_index("ix_calendar_events_project_id", "calendar_events", ["project_id"])

    op.create_table(
        "calendar_event_assignees",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("installer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["calendar_events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["installer_id"], ["installers.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "company_id", "event_id", "installer_id",
            name="uq_calendar_event_assignee",
        ),
    )
    op.create_index(
        "ix_calendar_event_assignees_company_id",
        "calendar_event_assignees",
        ["company_id"],
    )
    op.create_index(
        "ix_calendar_event_assignees_event_id",
        "calendar_event_assignees",
        ["event_id"],
    )
    op.create_index(
        "ix_calendar_event_assignees_installer_id",
        "calendar_event_assignees",
        ["installer_id"],
    )


def downgrade() -> None:
    op.drop_table("calendar_event_assignees")
    op.drop_table("calendar_events")
    postgresql.ENUM(
        "installation",
        "delivery",
        "meeting",
        "consultation",
        "inspection",
        name="calendar_event_type",
    ).drop(op.get_bind(), checkfirst=True)
