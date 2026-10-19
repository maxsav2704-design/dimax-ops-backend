"""DIMAX AI company rules: owner-approved instructions the agent receives as company authority.

Every save is a new version (history is kept); the current version is the one the runner uses and
every reply records which version it saw.

Revision ID: 0082_ai_company_rules
Revises: 0081_ai_worker_claims
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0082_ai_company_rules"
down_revision = "0081_ai_worker_claims"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_company_rules",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("text", sa.String(4000), nullable=False),
        sa.Column("updated_by_user_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("company_id", "version", name="uq_ai_company_rules_version"),
    )
    op.create_index("ix_ai_company_rules_company_id", "ai_company_rules", ["company_id"])


def downgrade() -> None:
    op.drop_index("ix_ai_company_rules_company_id", table_name="ai_company_rules")
    op.drop_table("ai_company_rules")
