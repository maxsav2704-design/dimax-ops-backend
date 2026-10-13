"""Immutable administrator accrual of one separately factory-confirmed work."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0074_work_price_accruals"
down_revision = "0073_work_price_approvals"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("work_price_accruals",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        *[sa.Column(name, pg.UUID(as_uuid=True), nullable=False) for name in
          ("company_id", "approval_id", "completed_work_id", "request_id")],
        sa.Column("sync_event_id", pg.UUID(as_uuid=True)),
        sa.Column("sync_queue_item_id", pg.UUID(as_uuid=True)),
        sa.Column("actor_user_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("approval_hash", sa.String(64), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("snapshot", pg.JSONB(), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("accrued_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("company_id", "request_id", name="uq_work_accrual_request"),
        sa.UniqueConstraint("company_id", "approval_id", name="uq_work_accrual_approval"),
        sa.UniqueConstraint("company_id", "sync_event_id", name="uq_work_accrual_event"),
        sa.UniqueConstraint("company_id", "sync_queue_item_id", name="uq_work_accrual_queue"),
        sa.UniqueConstraint("completed_work_id", name="uq_work_accrual_work"),
        *[sa.ForeignKeyConstraint(["company_id", column], [table + ".company_id", table + ".id"],
             ondelete="RESTRICT", name="fk_work_accrual_" + suffix) for column, table, suffix in (
                 ("approval_id", "work_price_approvals", "approval"),
                 ("completed_work_id", "completed_work", "work"),
                 ("sync_event_id", "sync_events", "event"),
                 ("sync_queue_item_id", "sync_queue_items", "queue"))],
        sa.CheckConstraint("(sync_event_id IS NULL) <> (sync_queue_item_id IS NULL)", name="ck_work_accrual_source"),
        sa.CheckConstraint("amount > 0 AND length(btrim(reason)) BETWEEN 10 AND 500", name="ck_work_accrual_values"),
        sa.CheckConstraint("length(request_fingerprint) = 64 AND length(approval_hash) = 64", name="ck_work_accrual_hashes"),
    )
    op.execute("""CREATE FUNCTION protect_work_price_accrual() RETURNS trigger AS $$
    BEGIN RAISE EXCEPTION 'Work price accrual evidence is immutable'; END;
    $$ LANGUAGE plpgsql""")
    op.execute("CREATE TRIGGER work_price_accrual_guard BEFORE UPDATE OR DELETE ON work_price_accruals FOR EACH ROW EXECUTE FUNCTION protect_work_price_accrual()")
    op.execute("""CREATE FUNCTION protect_work_accrued_earning() RETURNS trigger AS $$
    BEGIN
      IF EXISTS (SELECT 1 FROM work_price_accruals WHERE completed_work_id = OLD.id
                 OR completed_work_id = OLD.correction_ref_id) THEN
        IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'Factory-confirmed work earnings are immutable'; END IF;
        IF NEW IS DISTINCT FROM OLD THEN RAISE EXCEPTION 'Factory-confirmed work earnings are immutable'; END IF;
      END IF;
      IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql""")
    op.execute("CREATE TRIGGER work_accrued_earning_guard BEFORE UPDATE OR DELETE ON completed_work FOR EACH ROW EXECUTE FUNCTION protect_work_accrued_earning()")


def downgrade():
    op.execute("LOCK TABLE work_price_accruals IN ACCESS EXCLUSIVE MODE")
    if op.get_bind().execute(sa.text("SELECT EXISTS(SELECT 1 FROM work_price_accruals)")).scalar_one():
        raise RuntimeError("Cannot downgrade: work price accrual history exists")
    op.execute("DROP TRIGGER work_accrued_earning_guard ON completed_work")
    op.execute("DROP FUNCTION protect_work_accrued_earning()")
    op.drop_table("work_price_accruals")
    op.execute("DROP FUNCTION protect_work_price_accrual()")
