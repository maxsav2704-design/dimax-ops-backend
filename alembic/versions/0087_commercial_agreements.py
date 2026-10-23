"""Commercial agreements: an OWNER puts a factory-confirmed pair of versions into effect from a date.

Gap-free per contract (a new agreement closes the previous one the day before), one activation per
factory decision, never before the accounting start on 2026-11-10, immutable except for closing.
No claim, invoice, payment or installer earning is created by this table.

Revision ID: 0087_commercial_agreements
Revises: 0086_commercial_approvals
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0087_commercial_agreements"
down_revision = "0086_commercial_approvals"
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint("uq_commercial_approval_contract_id", "commercial_approvals",
                                ["company_id", "contract_id", "id"])
    op.create_table(
        "commercial_agreements",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        *[sa.Column(name, pg.UUID(as_uuid=True), nullable=False) for name in
          ("company_id", "contract_id", "terms_id", "price_id", "approval_id", "request_id")],
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_until", sa.Date()),
        sa.Column("activated_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("activated_by_name", sa.String(255), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(["company_id", "contract_id", "terms_id"],
            ["commercial_contract_terms.company_id", "commercial_contract_terms.contract_id", "commercial_contract_terms.id"],
            ondelete="RESTRICT", name="fk_commercial_agreement_terms"),
        sa.ForeignKeyConstraint(["company_id", "contract_id", "price_id"],
            ["commercial_price_versions.company_id", "commercial_price_versions.contract_id", "commercial_price_versions.id"],
            ondelete="RESTRICT", name="fk_commercial_agreement_price"),
        sa.ForeignKeyConstraint(["company_id", "contract_id", "approval_id"],
            ["commercial_approvals.company_id", "commercial_approvals.contract_id", "commercial_approvals.id"],
            ondelete="RESTRICT", name="fk_commercial_agreement_approval"),
        sa.UniqueConstraint("company_id", "request_id", name="uq_commercial_agreement_request"),
        sa.UniqueConstraint("approval_id", name="uq_commercial_agreement_approval"),
        sa.CheckConstraint("effective_until IS NULL OR effective_until >= effective_from", name="ck_commercial_agreement_dates"),
        sa.CheckConstraint("effective_from >= DATE '2026-11-10'", name="ck_commercial_agreement_cutover"),
        sa.CheckConstraint("btrim(reason) <> '' AND btrim(activated_by_name) <> ''", name="ck_commercial_agreement_labels"),
    )
    op.create_index("uq_commercial_agreement_open", "commercial_agreements", ["contract_id"], unique=True,
                    postgresql_where=sa.text("effective_until IS NULL"))
    op.create_index("ix_commercial_agreement_lookup", "commercial_agreements", ["company_id", "contract_id", "effective_from"])
    op.execute("""
        CREATE FUNCTION guard_commercial_agreement() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Commercial agreement history cannot be deleted' USING ERRCODE = '23000';
            END IF;
            IF TG_OP = 'UPDATE' THEN
                IF OLD.effective_until IS NOT NULL OR NEW.effective_until IS NULL
                   OR (to_jsonb(NEW) - 'effective_until') IS DISTINCT FROM (to_jsonb(OLD) - 'effective_until') THEN
                    RAISE EXCEPTION 'A commercial agreement is immutable; only an open agreement may be closed' USING ERRCODE = '23000';
                END IF;
                RETURN NEW;
            END IF;
            IF EXISTS (
                SELECT 1 FROM commercial_agreements other
                WHERE other.contract_id = NEW.contract_id AND other.id <> NEW.id
                  AND daterange(other.effective_from, COALESCE(other.effective_until, 'infinity'::date), '[]')
                      && daterange(NEW.effective_from, COALESCE(NEW.effective_until, 'infinity'::date), '[]')
            ) THEN
                RAISE EXCEPTION 'Commercial agreements of one contract cannot overlap' USING ERRCODE = '23000';
            END IF;
            RETURN NEW;
        END; $$ LANGUAGE plpgsql;
        CREATE TRIGGER commercial_agreement_guard BEFORE INSERT OR UPDATE OR DELETE ON commercial_agreements
            FOR EACH ROW EXECUTE FUNCTION guard_commercial_agreement();
    """)


def downgrade():
    op.execute("LOCK TABLE commercial_agreements, audit_logs IN ACCESS EXCLUSIVE MODE")
    if op.get_bind().execute(sa.text("SELECT EXISTS(SELECT 1 FROM commercial_agreements) "
            "OR EXISTS(SELECT 1 FROM audit_logs WHERE entity_type='COMMERCIAL_AGREEMENT')")).scalar_one():
        raise RuntimeError("Cannot discard commercial agreement history")
    op.execute("DROP TRIGGER commercial_agreement_guard ON commercial_agreements")
    op.execute("DROP FUNCTION guard_commercial_agreement()")
    op.drop_index("ix_commercial_agreement_lookup", table_name="commercial_agreements")
    op.drop_index("uq_commercial_agreement_open", table_name="commercial_agreements")
    op.drop_table("commercial_agreements")
    op.drop_constraint("uq_commercial_approval_contract_id", "commercial_approvals", type_="unique")
