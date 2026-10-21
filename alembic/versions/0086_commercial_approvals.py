"""Factory decisions bind exact commercial terms and price versions; no activation.

Revision ID: 0086_commercial_approvals
Revises: 0085_commercial_terms
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0086_commercial_approvals"
down_revision = "0085_commercial_terms"
branch_labels = None
depends_on = None


def upgrade():
    for table, name in (("commercial_contract_terms", "uq_commercial_terms_contract_id"),
                        ("commercial_price_versions", "uq_commercial_price_contract_id")):
        op.create_unique_constraint(name, table, ["company_id", "contract_id", "id"])
    op.create_table("commercial_approvals",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        *[sa.Column(name, pg.UUID(as_uuid=True), nullable=False) for name in
          ("company_id", "contract_id", "terms_id", "price_id", "factory_contact_id", "request_id")],
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
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT")),
        sa.Column("revocation_reason", sa.String(1000)),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("confirmed_name", sa.String(160)),
        sa.Column("mailbox_challenge_id", pg.UUID(as_uuid=True)),
        sa.Column("mailbox_code_hash", sa.String(64)),
        *[sa.Column(name, sa.DateTime(timezone=True)) for name in
          ("mailbox_code_expires_at", "mailbox_requested_at", "mailbox_verified_at")],
        sa.Column("mailbox_requests", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("mailbox_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["company_id", "contract_id", "terms_id"],
            ["commercial_contract_terms.company_id", "commercial_contract_terms.contract_id", "commercial_contract_terms.id"],
            ondelete="RESTRICT", name="fk_commercial_approval_terms"),
        sa.ForeignKeyConstraint(["company_id", "contract_id", "price_id"],
            ["commercial_price_versions.company_id", "commercial_price_versions.contract_id", "commercial_price_versions.id"],
            ondelete="RESTRICT", name="fk_commercial_approval_price"),
        sa.ForeignKeyConstraint(["company_id", "factory_contact_id"], ["factory_contacts.company_id", "factory_contacts.id"],
            ondelete="RESTRICT", name="fk_commercial_approval_contact"),
        sa.UniqueConstraint("token_hash"),
        sa.UniqueConstraint("company_id", "request_id", name="uq_commercial_approval_request"),
        sa.CheckConstraint("expires_at > created_at", name="ck_commercial_approval_expiry"),
        sa.CheckConstraint("mailbox_requests BETWEEN 0 AND 10 AND mailbox_attempts BETWEEN 0 AND 5", name="ck_commercial_approval_limits"),
        sa.CheckConstraint("(mailbox_code_hash IS NULL AND mailbox_challenge_id IS NULL AND mailbox_code_expires_at IS NULL AND mailbox_requested_at IS NULL) OR (mailbox_code_hash IS NOT NULL AND mailbox_challenge_id IS NOT NULL AND mailbox_code_expires_at IS NOT NULL AND mailbox_requested_at IS NOT NULL AND mailbox_code_expires_at > mailbox_requested_at AND mailbox_requests > 0)", name="ck_commercial_approval_challenge"),
        sa.CheckConstraint("(confirmed_at IS NULL AND confirmed_name IS NULL AND mailbox_verified_at IS NULL) OR (confirmed_at IS NOT NULL AND confirmed_name IS NOT NULL AND btrim(confirmed_name) <> '' AND mailbox_verified_at = confirmed_at AND mailbox_verified_at IS NOT NULL AND mailbox_code_hash IS NOT NULL AND confirmed_at < expires_at AND revoked_at IS NULL)", name="ck_commercial_approval_confirmation"),
        sa.CheckConstraint("(revoked_at IS NULL AND revoked_by IS NULL AND revocation_reason IS NULL) OR (revoked_at IS NOT NULL AND revoked_by IS NOT NULL AND revocation_reason IS NOT NULL AND btrim(revocation_reason) <> '' AND confirmed_at IS NULL)", name="ck_commercial_approval_revocation"),
    )
    op.create_index("uq_commercial_approval_pending", "commercial_approvals", ["contract_id"], unique=True,
                    postgresql_where=sa.text("revoked_at IS NULL AND confirmed_at IS NULL"))
    op.create_index("uq_commercial_approval_confirmed", "commercial_approvals", ["terms_id", "price_id"], unique=True,
                    postgresql_where=sa.text("confirmed_at IS NOT NULL"))
    op.create_index("ix_commercial_approval_history", "commercial_approvals", ["company_id", "contract_id", "created_at"])
    op.drop_constraint("ck_audit_external_factory_actor", "audit_logs", type_="check")
    op.create_check_constraint("ck_audit_external_factory_actor", "audit_logs",
        "actor_user_id IS NOT NULL OR (entity_type IN ('FACTORY_PRICE_APPROVAL', 'WORK_PRICE_APPROVAL', 'COMMERCIAL_APPROVAL') "
        "AND action = 'CONFIRM' AND coalesce(after->>'actor_kind', '') = 'FACTORY_REPRESENTATIVE' "
        "AND coalesce(after->>'factory_contact_id', '') <> '') "
        "OR (entity_type = 'import_inbox' AND coalesce(after->>'source', '') IN ('FOLDER', 'EMAIL'))")
    op.execute("""
        CREATE FUNCTION guard_commercial_approval() RETURNS trigger AS $$
        DECLARE mutable text[] := ARRAY['revoked_at','revoked_by','revocation_reason',
            'confirmed_at','confirmed_name','mailbox_verified_at','mailbox_challenge_id',
            'mailbox_code_hash','mailbox_code_expires_at','mailbox_requested_at','mailbox_requests','mailbox_attempts'];
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Commercial approval history cannot be deleted' USING ERRCODE = '23000';
            END IF;
            IF (to_jsonb(NEW) - mutable) IS DISTINCT FROM (to_jsonb(OLD) - mutable)
               OR ((OLD.confirmed_at IS NOT NULL OR OLD.revoked_at IS NOT NULL) AND NEW IS DISTINCT FROM OLD) THEN
                RAISE EXCEPTION 'Commercial evidence is immutable' USING ERRCODE = '23000';
            END IF;
            RETURN NEW;
        END; $$ LANGUAGE plpgsql;
        CREATE TRIGGER commercial_approval_immutable BEFORE UPDATE OR DELETE ON commercial_approvals
            FOR EACH ROW EXECUTE FUNCTION guard_commercial_approval();

        CREATE FUNCTION guard_invited_commercial_price() RETURNS trigger AS $$
        DECLARE price uuid;
        BEGIN
            IF TG_TABLE_NAME = 'commercial_price_versions' THEN price := OLD.id;
            ELSIF TG_OP = 'INSERT' THEN price := NEW.price_version_id;
            ELSE price := OLD.price_version_id; END IF;
            IF EXISTS (SELECT 1 FROM commercial_approvals WHERE price_id = price)
               OR (TG_OP = 'UPDATE' AND TG_TABLE_NAME = 'commercial_price_items'
                   AND EXISTS (SELECT 1 FROM commercial_approvals WHERE price_id = (to_jsonb(NEW)->>'price_version_id')::uuid)) THEN
                RAISE EXCEPTION 'Invited commercial price is immutable; create a new version' USING ERRCODE = '23000';
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END; $$ LANGUAGE plpgsql;
        CREATE TRIGGER commercial_price_invited BEFORE UPDATE OR DELETE ON commercial_price_versions
            FOR EACH ROW EXECUTE FUNCTION guard_invited_commercial_price();
        CREATE TRIGGER commercial_item_invited BEFORE INSERT OR UPDATE OR DELETE ON commercial_price_items
            FOR EACH ROW EXECUTE FUNCTION guard_invited_commercial_price();
    """)


def downgrade():
    op.execute("LOCK TABLE commercial_approvals, audit_logs IN ACCESS EXCLUSIVE MODE")
    if op.get_bind().execute(sa.text("SELECT EXISTS(SELECT 1 FROM commercial_approvals) "
            "OR EXISTS(SELECT 1 FROM audit_logs WHERE entity_type='COMMERCIAL_APPROVAL')")).scalar_one():
        raise RuntimeError("Cannot discard commercial confirmation history")
    op.drop_constraint("ck_audit_external_factory_actor", "audit_logs", type_="check")
    op.create_check_constraint("ck_audit_external_factory_actor", "audit_logs",
        "actor_user_id IS NOT NULL OR (entity_type IN ('FACTORY_PRICE_APPROVAL', 'WORK_PRICE_APPROVAL') "
        "AND action = 'CONFIRM' AND coalesce(after->>'actor_kind', '') = 'FACTORY_REPRESENTATIVE' "
        "AND coalesce(after->>'factory_contact_id', '') <> '') "
        "OR (entity_type = 'import_inbox' AND coalesce(after->>'source', '') IN ('FOLDER', 'EMAIL'))")
    op.execute("DROP TRIGGER commercial_item_invited ON commercial_price_items")
    op.execute("DROP TRIGGER commercial_price_invited ON commercial_price_versions")
    op.execute("DROP FUNCTION guard_invited_commercial_price()")
    op.drop_table("commercial_approvals")
    op.execute("DROP FUNCTION guard_commercial_approval()")
    op.drop_constraint("uq_commercial_price_contract_id", "commercial_price_versions", type_="unique")
    op.drop_constraint("uq_commercial_terms_contract_id", "commercial_contract_terms", type_="unique")
