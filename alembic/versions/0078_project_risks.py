"""System risks (installer sync, outbox delivery) live on the project.

They used to be stored as issues attached to an arbitrary door of the project,
which collided with the one-issue-per-door rule, reached the installer's device
and got closed by installing that door. Existing risk issues are moved into
project_risks (one row per project and kind) and removed from issues.

Revision ID: 0078_project_risks
Revises: 0077_issue_comments
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0078_project_risks"
down_revision = "0077_issue_comments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_risks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="OPEN"),
        sa.Column("details", sa.String(2000), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("company_id", "project_id", "kind", name="uq_project_risks_scope_kind"),
        if_not_exists=True,
    )
    op.create_index("ix_project_risks_company", "project_risks", ["company_id"], if_not_exists=True)
    op.create_index("ix_project_risks_project", "project_risks", ["project_id"], if_not_exists=True)

    # Move the door-bound system issues to the project (first one per project and kind wins).
    op.execute(
        """
        INSERT INTO project_risks (id, company_id, project_id, kind, status, details, opened_at, closed_at, created_at, updated_at)
        SELECT gen_random_uuid(), i.company_id, d.project_id,
               CASE i.title WHEN 'SYNC_RISK' THEN 'SYNC' ELSE 'DELIVERY_OUTBOX' END,
               CASE WHEN i.status::text = 'OPEN' THEN 'OPEN' ELSE 'CLOSED' END,
               i.details, i.created_at,
               CASE WHEN i.status::text = 'OPEN' THEN NULL ELSE i.updated_at END,
               now(), now()
        FROM issues i
        JOIN doors d ON d.id = i.door_id
        WHERE i.title IN ('SYNC_RISK', 'DELIVERY_OUTBOX_RISK')
        ORDER BY i.created_at
        ON CONFLICT (company_id, project_id, kind) DO NOTHING
        """
    )
    op.execute("DELETE FROM issues WHERE title IN ('SYNC_RISK', 'DELIVERY_OUTBOX_RISK')")


def downgrade() -> None:
    # The door-bound form is not restored: a project-level risk has no door.
    op.drop_index("ix_project_risks_project", table_name="project_risks", if_exists=True)
    op.drop_index("ix_project_risks_company", table_name="project_risks", if_exists=True)
    op.drop_table("project_risks", if_exists=True)
