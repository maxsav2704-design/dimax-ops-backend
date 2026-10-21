"""Document import inbox: factory files arrive (upload, watched folder, mailbox), the system
matches the project, analyzes and imports clean files by itself; the office only decides the rest.

Revision ID: 0083_import_inbox
Revises: 0082_ai_company_rules
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0083_import_inbox"
down_revision = "0082_ai_company_rules"
branch_labels = None
depends_on = None


OLD_ACTOR_CHECK = (
    "actor_user_id IS NOT NULL OR (entity_type IN ('FACTORY_PRICE_APPROVAL', 'WORK_PRICE_APPROVAL') AND action = 'CONFIRM' "
    "AND coalesce(after->>'actor_kind', '') = 'FACTORY_REPRESENTATIVE' AND coalesce(after->>'factory_contact_id', '') <> '')"
)
# Automatic inbox channels (watched folder, mailbox) act without a user; the audit row names the source instead.
NEW_ACTOR_CHECK = OLD_ACTOR_CHECK + " OR (entity_type = 'import_inbox' AND coalesce(after->>'source', '') IN ('FOLDER', 'EMAIL'))"


def upgrade() -> None:
    op.drop_constraint("ck_audit_external_factory_actor", "audit_logs", type_="check")
    op.create_check_constraint("ck_audit_external_factory_actor", "audit_logs", NEW_ACTOR_CHECK)
    op.add_column("companies", sa.Column("import_auto_commit", sa.Boolean(), nullable=False, server_default=sa.text("true")))
    op.create_table(
        "project_import_inbox",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", pg.UUID(as_uuid=True), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("source_ref", sa.String(255), nullable=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("object_key", sa.String(400), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("detected_profile", sa.String(64), nullable=True),
        sa.Column("order_numbers", pg.JSONB(), nullable=True),
        sa.Column("matched_project_id", pg.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="SET NULL"), nullable=True),
        sa.Column("match_reason", sa.String(32), nullable=True),
        sa.Column("candidate_project_ids", pg.JSONB(), nullable=True),
        sa.Column("analysis", pg.JSONB(), nullable=True),
        sa.Column("import_result", pg.JSONB(), nullable=True),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("created_by_user_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("decided_by_user_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("company_id", "content_sha256", name="uq_project_import_inbox_content"),
        sa.CheckConstraint("status IN ('NEW','ANALYZED','NEEDS_PROJECT','IMPORTED','FAILED','DISMISSED')", name="ck_project_import_inbox_status"),
    )
    op.create_index("ix_project_import_inbox_company_created", "project_import_inbox", ["company_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_project_import_inbox_company_created", table_name="project_import_inbox")
    op.drop_table("project_import_inbox")
    op.drop_column("companies", "import_auto_commit")
    op.execute("DELETE FROM audit_logs WHERE entity_type = 'import_inbox' AND actor_user_id IS NULL")
    op.drop_constraint("ck_audit_external_factory_actor", "audit_logs", type_="check")
    op.create_check_constraint("ck_audit_external_factory_actor", "audit_logs", OLD_ACTOR_CHECK)
