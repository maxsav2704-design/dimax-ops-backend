"""Publish existing and future door issues to incremental installer sync."""
from alembic import op

revision = "0062_issue_sync"
down_revision = "0061_journal_pdf_locale"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL requires the new enum value to commit before its first use.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE sync_change_type ADD VALUE IF NOT EXISTS 'ISSUE'")
    op.execute("""
        INSERT INTO sync_change_log
            (created_at, company_id, change_type, entity_id, project_id, installer_id, payload)
        SELECT now(), i.company_id, 'ISSUE', i.id, d.project_id, d.installer_id,
            jsonb_build_object('id', i.id, 'door_id', d.id, 'project_id', d.project_id,
                'status', i.status::text, 'title', i.title, 'details', i.details)
        FROM issues i
        JOIN doors d ON d.id = i.door_id AND d.company_id = i.company_id
        JOIN projects p ON p.id = d.project_id AND p.company_id = i.company_id
        WHERE d.installer_id IS NOT NULL AND p.deleted_at IS NULL
    """)


def downgrade() -> None:
    # Older ORM enums cannot read these derived events; business rows remain intact.
    op.execute("DELETE FROM sync_change_log WHERE change_type = 'ISSUE'")
    # Keep the additive PostgreSQL enum value, as in revision 0017.
