"""Immutable draft snapshots of factory identity and contract terms.

Revision ID: 0085_commercial_terms
Revises: 0084_commercial_drafts
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0085_commercial_terms"
down_revision = "0084_commercial_drafts"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "commercial_contract_terms",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("contract_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("factory_legal_name", sa.String(200), nullable=False),
        sa.Column("registration_number", sa.String(80), nullable=False),
        sa.Column("address", sa.String(1000), nullable=False),
        sa.Column("contact_name", sa.String(200)),
        sa.Column("contact_email", sa.String(254)),
        sa.Column("contact_phone", sa.String(40)),
        sa.Column("proposed_from", sa.Date(), nullable=False),
        sa.Column("proposed_until", sa.Date()),
        sa.Column("billing_basis", sa.String(24), nullable=False),
        sa.Column("payment_terms", sa.String(4000), nullable=False),
        sa.Column("retention_terms", sa.String(4000), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("agreement_reference", sa.String(200), nullable=False),
        sa.Column("request_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("created_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_by_name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id", "contract_id"],
                                ["commercial_contracts.company_id", "commercial_contracts.id"],
                                name="fk_commercial_terms_contract", ondelete="RESTRICT"),
        sa.UniqueConstraint("company_id", "contract_id", "version", name="uq_commercial_terms_version"),
        sa.UniqueConstraint("company_id", "request_id", name="uq_commercial_terms_request"),
        sa.CheckConstraint("version > 0 AND status = 'DRAFT'", name="ck_commercial_terms_draft"),
        sa.CheckConstraint("billing_basis IN ('FULL_INSTALLATION', 'STAGES')", name="ck_commercial_terms_basis"),
        sa.CheckConstraint("proposed_until IS NULL OR proposed_until >= proposed_from", name="ck_commercial_terms_dates"),
        sa.CheckConstraint(
            "btrim(factory_legal_name) <> '' AND btrim(registration_number) <> '' AND btrim(address) <> '' "
            "AND btrim(payment_terms) <> '' AND btrim(retention_terms) <> '' "
            "AND btrim(reason) <> '' AND btrim(agreement_reference) <> ''",
            name="ck_commercial_terms_labels",
        ),
    )
    op.execute("""
        CREATE FUNCTION reject_commercial_terms_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Contract terms are immutable; create a new version'
                USING ERRCODE = '23000';
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER commercial_terms_immutable BEFORE UPDATE OR DELETE
        ON commercial_contract_terms FOR EACH ROW
        EXECUTE FUNCTION reject_commercial_terms_mutation();
    """)


def downgrade():
    op.drop_table("commercial_contract_terms")
    op.execute("DROP FUNCTION reject_commercial_terms_mutation()")
