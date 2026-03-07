"""Add issue workflow assignment fields.

Revision ID: 0027_issue_workflow_fields
Revises: 0026_project_import_runs
Create Date: 2026-02-25
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0027_issue_workflow_fields"
down_revision = "0026_project_import_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    issue_priority = postgresql.ENUM("P1", "P2", "P3", "P4", name="issue_priority")
    issue_workflow_state = postgresql.ENUM(
        "NEW",
        "TRIAGED",
        "IN_PROGRESS",
        "BLOCKED",
        "RESOLVED",
        "CLOSED",
        name="issue_workflow_state",
    )
    issue_priority.create(op.get_bind(), checkfirst=True)
    issue_workflow_state.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "issues",
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "issues",
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "issues",
        sa.Column(
            "priority",
            issue_priority,
            nullable=False,
            server_default="P3",
        ),
    )
    op.add_column(
        "issues",
        sa.Column(
            "workflow_state",
            issue_workflow_state,
            nullable=False,
            server_default="NEW",
        ),
    )
    op.create_foreign_key(
        "fk_issues_owner_user_id_users",
        "issues",
        "users",
        ["owner_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_issues_owner_user_id", "issues", ["owner_user_id"])
    op.create_index("ix_issues_due_at", "issues", ["due_at"])
    op.create_index("ix_issues_priority", "issues", ["priority"])
    op.create_index("ix_issues_workflow_state", "issues", ["workflow_state"])


def downgrade() -> None:
    op.drop_index("ix_issues_workflow_state", table_name="issues")
    op.drop_index("ix_issues_priority", table_name="issues")
    op.drop_index("ix_issues_due_at", table_name="issues")
    op.drop_index("ix_issues_owner_user_id", table_name="issues")
    op.drop_constraint("fk_issues_owner_user_id_users", "issues", type_="foreignkey")
    op.drop_column("issues", "workflow_state")
    op.drop_column("issues", "priority")
    op.drop_column("issues", "due_at")
    op.drop_column("issues", "owner_user_id")

    postgresql.ENUM(name="issue_workflow_state").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="issue_priority").drop(op.get_bind(), checkfirst=True)
