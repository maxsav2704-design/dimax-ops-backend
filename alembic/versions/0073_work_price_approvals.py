"""Separate mailbox-verified factory decisions for retained work. No accrual."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0073_work_price_approvals"
down_revision = "0072_work_price_proposals"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("work_price_approvals",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        *[sa.Column(name, pg.UUID(as_uuid=True), nullable=False) for name in
          ("company_id", "proposal_id", "factory_contact_id", "request_id")],
        *[sa.Column(name, sa.String(64), nullable=False) for name in
          ("request_fingerprint", "token_hash", "snapshot_hash")],
        sa.Column("snapshot", pg.JSONB(), nullable=False),
        sa.Column("factory_name", sa.String(160), nullable=False),
        sa.Column("recipient_name", sa.String(160), nullable=False),
        sa.Column("recipient_email", sa.String(320), nullable=False),
        sa.Column("created_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("email_outbox_id", pg.UUID(as_uuid=True), sa.ForeignKey("outbox_messages.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("revoked_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT")),
        sa.Column("revocation_reason", sa.String(1000)),
        sa.Column("confirmed_name", sa.String(160)),
        sa.Column("mailbox_challenge_id", pg.UUID(as_uuid=True)),
        sa.Column("mailbox_code_hash", sa.String(64)),
        *[sa.Column(name, sa.DateTime(timezone=True)) for name in
          ("revoked_at", "confirmed_at", "mailbox_code_expires_at", "mailbox_requested_at", "mailbox_verified_at")],
        sa.Column("mailbox_requests", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("mailbox_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("token_hash"),
        sa.UniqueConstraint("company_id", "id", name="uq_work_approval_tenant"),
        sa.UniqueConstraint("company_id", "request_id", name="uq_work_approval_request"),
        sa.ForeignKeyConstraint(["company_id", "proposal_id"], ["work_price_proposals.company_id", "work_price_proposals.id"], ondelete="RESTRICT", name="fk_work_approval_proposal"),
        sa.ForeignKeyConstraint(["company_id", "factory_contact_id"], ["factory_contacts.company_id", "factory_contacts.id"], ondelete="RESTRICT", name="fk_work_approval_contact"),
        sa.CheckConstraint("expires_at > created_at", name="ck_work_approval_expiry"),
        sa.CheckConstraint("mailbox_requests BETWEEN 0 AND 10 AND mailbox_attempts BETWEEN 0 AND 5", name="ck_work_approval_limits"),
        sa.CheckConstraint("(mailbox_code_hash IS NULL AND mailbox_challenge_id IS NULL AND mailbox_code_expires_at IS NULL AND mailbox_requested_at IS NULL) OR (mailbox_code_hash IS NOT NULL AND mailbox_challenge_id IS NOT NULL AND mailbox_code_expires_at IS NOT NULL AND mailbox_requested_at IS NOT NULL AND mailbox_code_expires_at > mailbox_requested_at AND mailbox_requests > 0)", name="ck_work_approval_challenge"),
        sa.CheckConstraint("(confirmed_at IS NULL AND confirmed_name IS NULL AND mailbox_verified_at IS NULL) OR (confirmed_at IS NOT NULL AND confirmed_name IS NOT NULL AND btrim(confirmed_name) <> '' AND mailbox_verified_at IS NOT NULL AND mailbox_verified_at = confirmed_at AND mailbox_code_hash IS NOT NULL AND confirmed_at < expires_at AND revoked_at IS NULL)", name="ck_work_approval_confirmation"),
        sa.CheckConstraint("(revoked_at IS NULL AND revoked_by IS NULL AND revocation_reason IS NULL) OR (revoked_at IS NOT NULL AND revoked_by IS NOT NULL AND revocation_reason IS NOT NULL AND btrim(revocation_reason) <> '' AND confirmed_at IS NULL)", name="ck_work_approval_revocation"),
    )
    op.create_index("uq_work_approval_pending", "work_price_approvals", ["proposal_id"], unique=True,
                    postgresql_where=sa.text("revoked_at IS NULL AND confirmed_at IS NULL"))
    op.create_index("uq_work_approval_confirmed", "work_price_approvals", ["proposal_id"], unique=True,
                    postgresql_where=sa.text("confirmed_at IS NOT NULL"))
    # Terms never change. Challenge/revocation fields may change only before a decision.
    op.execute("""CREATE FUNCTION protect_work_price_approval() RETURNS trigger AS $$
    BEGIN
      IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'Work price invitation history is immutable'; END IF;
      IF OLD.confirmed_at IS NOT NULL OR OLD.revoked_at IS NOT NULL THEN
        IF NEW IS DISTINCT FROM OLD THEN RAISE EXCEPTION 'Work price decision is immutable'; END IF;
      END IF;
      IF (to_jsonb(NEW) - ARRAY['revoked_at','revoked_by','revocation_reason','confirmed_at','confirmed_name',
          'mailbox_challenge_id','mailbox_code_hash','mailbox_code_expires_at','mailbox_requested_at',
          'mailbox_requests','mailbox_attempts','mailbox_verified_at']) IS DISTINCT FROM
         (to_jsonb(OLD) - ARRAY['revoked_at','revoked_by','revocation_reason','confirmed_at','confirmed_name',
          'mailbox_challenge_id','mailbox_code_hash','mailbox_code_expires_at','mailbox_requested_at',
          'mailbox_requests','mailbox_attempts','mailbox_verified_at']) THEN
        RAISE EXCEPTION 'Work price invitation terms are immutable';
      END IF;
      IF NEW.mailbox_requests < OLD.mailbox_requests OR NEW.mailbox_attempts < OLD.mailbox_attempts THEN
        RAISE EXCEPTION 'Mailbox limits cannot be reset';
      END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql""")
    op.execute("CREATE TRIGGER work_price_approval_guard BEFORE UPDATE OR DELETE ON work_price_approvals FOR EACH ROW EXECUTE FUNCTION protect_work_price_approval()")
    op.drop_constraint("ck_audit_external_factory_actor", "audit_logs", type_="check")
    op.create_check_constraint("ck_audit_external_factory_actor", "audit_logs",
        "actor_user_id IS NOT NULL OR (entity_type IN ('FACTORY_PRICE_APPROVAL', 'WORK_PRICE_APPROVAL') AND action = 'CONFIRM' AND coalesce(after->>'actor_kind', '') = 'FACTORY_REPRESENTATIVE' AND coalesce(after->>'factory_contact_id', '') <> '')")


def downgrade():
    op.execute("LOCK TABLE work_price_approvals, audit_logs IN ACCESS EXCLUSIVE MODE")
    if op.get_bind().execute(sa.text("SELECT EXISTS(SELECT 1 FROM work_price_approvals) OR EXISTS(SELECT 1 FROM audit_logs WHERE entity_type='WORK_PRICE_APPROVAL')")).scalar_one():
        raise RuntimeError("Cannot downgrade: work price invitation history exists")
    op.drop_constraint("ck_audit_external_factory_actor", "audit_logs", type_="check")
    op.create_check_constraint("ck_audit_external_factory_actor", "audit_logs",
        "actor_user_id IS NOT NULL OR (entity_type = 'FACTORY_PRICE_APPROVAL' AND action = 'CONFIRM' AND coalesce(after->>'actor_kind', '') = 'FACTORY_REPRESENTATIVE' AND coalesce(after->>'factory_contact_id', '') <> '')")
    op.drop_table("work_price_approvals")
    op.execute("DROP FUNCTION protect_work_price_approval()")
