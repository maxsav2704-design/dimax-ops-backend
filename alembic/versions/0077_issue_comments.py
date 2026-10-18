"""Issue comments: the office and the installer talk on the issue without
overwriting each other's text.

Revision ID: 0077_issue_comments
Revises: 0076_ledger_immutability
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0077_issue_comments"
down_revision = "0076_ledger_immutability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "issue_comments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("issue_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("issues.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("author_role", sa.String(16), nullable=False),
        sa.Column("author_name", sa.String(255), nullable=True),
        sa.Column("body", sa.String(2000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        if_not_exists=True,
    )
    op.create_index("ix_issue_comments_issue_created", "issue_comments", ["issue_id", "created_at"], if_not_exists=True)
    op.create_index("ix_issue_comments_company", "issue_comments", ["company_id"], if_not_exists=True)


def downgrade() -> None:
    op.drop_index("ix_issue_comments_company", table_name="issue_comments", if_exists=True)
    op.drop_index("ix_issue_comments_issue_created", table_name="issue_comments", if_exists=True)
    op.drop_table("issue_comments", if_exists=True)
