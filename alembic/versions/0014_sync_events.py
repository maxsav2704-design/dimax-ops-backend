"""sync events for offline outbox

Revision ID: 0014_sync_events
Revises: 0013_addons
Create Date: 2026-02-13

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0014_sync_events"
down_revision = "0013_addons"
branch_labels = None
depends_on = None


def upgrade() -> None:
    event_type = postgresql.ENUM(
        "DOOR_SET_STATUS", "ADDON_FACT_CREATE", name="sync_event_type", create_type=False
    )
    event_type.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "sync_events",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("installer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", event_type, nullable=False),
        sa.Column("client_event_id", sa.String(length=80), nullable=False),
        sa.Column(
            "client_happened_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("apply_error", sa.Text(), nullable=True),
    )

    op.create_index(
        "ix_sync_events_company_project",
        "sync_events",
        ["company_id", "project_id"],
    )
    op.create_index(
        "ix_sync_events_company_installer",
        "sync_events",
        ["company_id", "installer_id"],
    )
    op.create_index("ix_sync_events_created_at", "sync_events", ["created_at"])
    op.create_unique_constraint(
        "uq_sync_events_client_event",
        "sync_events",
        ["company_id", "client_event_id"],
    )


def downgrade() -> None:
    op.drop_table("sync_events")
    postgresql.ENUM(name="sync_event_type").drop(
        op.get_bind(), checkfirst=True
    )
