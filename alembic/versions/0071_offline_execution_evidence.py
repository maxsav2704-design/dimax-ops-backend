"""Server-owned assignment boundaries and original client clock evidence.

Revision ID: 0071_offline_evidence
Revises: 0070_factory_contact
"""
from alembic import op
import sqlalchemy as sa

revision = "0071_offline_evidence"
down_revision = "0070_factory_contact"
branch_labels = None
depends_on = None


def upgrade():
    # NULL deliberately means unknown history for assignments predating this migration.
    op.add_column("doors", sa.Column("assignment_started_at", sa.DateTime(timezone=True), nullable=True))
    for table in ("sync_events", "sync_queue_items"):
        op.add_column(table, sa.Column("client_time_has_timezone", sa.Boolean(), nullable=True))
    op.execute("""
        CREATE FUNCTION dimax_door_assignment_boundary() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                NEW.assignment_started_at := CASE WHEN NEW.installer_id IS NOT NULL THEN clock_timestamp() END;
            ELSIF NEW.installer_id IS DISTINCT FROM OLD.installer_id
               OR NEW.project_id IS DISTINCT FROM OLD.project_id
               OR NEW.company_id IS DISTINCT FROM OLD.company_id THEN
                NEW.assignment_started_at := CASE WHEN NEW.installer_id IS NOT NULL THEN clock_timestamp() END;
            ELSE
                NEW.assignment_started_at := OLD.assignment_started_at;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER door_assignment_boundary BEFORE INSERT OR UPDATE ON doors
            FOR EACH ROW EXECUTE FUNCTION dimax_door_assignment_boundary();
    """)


def downgrade():
    op.execute("LOCK TABLE doors, sync_events, sync_queue_items IN ACCESS EXCLUSIVE MODE")
    if op.get_bind().execute(sa.text("SELECT EXISTS (SELECT 1 FROM doors WHERE assignment_started_at IS NOT NULL) "
        "OR EXISTS (SELECT 1 FROM sync_events WHERE client_time_has_timezone IS NOT NULL) "
        "OR EXISTS (SELECT 1 FROM sync_queue_items WHERE client_time_has_timezone IS NOT NULL)")).scalar():
        raise RuntimeError("Cannot discard recorded offline execution evidence")
    op.execute("DROP TRIGGER door_assignment_boundary ON doors")
    op.execute("DROP FUNCTION dimax_door_assignment_boundary()")
    for table in ("sync_events", "sync_queue_items"):
        op.drop_column(table, "client_time_has_timezone")
    op.drop_column("doors", "assignment_started_at")
