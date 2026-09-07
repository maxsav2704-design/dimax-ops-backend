"""Allow installer issue creation through the offline sync outbox.

Revision ID: 0054_sync_issue_create_event
Revises: 0053_document_templates
Create Date: 2026-06-20

"""
from __future__ import annotations

from alembic import op


revision = "0054_sync_issue_create_event"
down_revision = "0053_document_templates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE sync_event_type ADD VALUE IF NOT EXISTS 'ISSUE_CREATE'")


def downgrade() -> None:
    # PostgreSQL enum values cannot be removed safely while rows may reference them.
    pass
