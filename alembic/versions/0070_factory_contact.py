"""Owner-authorized factory recipients and external confirmation audit identity."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0070_factory_contact"
down_revision = "0069_factory_mailbox"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("factory_contacts",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", pg.UUID(as_uuid=True), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("factory_name", sa.String(160), nullable=False),
        sa.Column("recipient_name", sa.String(160), nullable=False),
        sa.Column("recipient_email", sa.String(320), nullable=False),
        sa.Column("authority_reference", sa.String(500), nullable=False),
        sa.Column("approved_by", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_by", pg.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("company_id", "id", name="uq_factory_contacts_tenant_id"),
        sa.CheckConstraint("btrim(factory_name) <> '' AND btrim(recipient_name) <> '' AND btrim(recipient_email) <> '' "
                           "AND btrim(authority_reference) <> ''", name="ck_factory_contacts_identity"),
        sa.CheckConstraint("(revoked_at IS NULL AND revoked_by IS NULL) OR "
                           "(revoked_at IS NOT NULL AND revoked_by IS NOT NULL)", name="ck_factory_contacts_revocation"))
    op.create_index("uq_factory_contacts_current", "factory_contacts", ["company_id"], unique=True,
                    postgresql_where=sa.text("revoked_at IS NULL"))
    # Do not manufacture owner authorization for historical invitations or decisions.
    op.add_column("factory_price_approvals", sa.Column("factory_contact_id", pg.UUID(as_uuid=True)))
    op.create_foreign_key("fk_factory_approvals_contact", "factory_price_approvals", "factory_contacts",
                          ["company_id", "factory_contact_id"], ["company_id", "id"], ondelete="RESTRICT")
    op.alter_column("audit_logs", "actor_user_id", nullable=True)
    op.create_check_constraint("ck_audit_external_factory_actor", "audit_logs",
        "actor_user_id IS NOT NULL OR (entity_type = 'FACTORY_PRICE_APPROVAL' AND action = 'CONFIRM' "
        "AND coalesce(after->>'actor_kind', '') = 'FACTORY_REPRESENTATIVE' "
        "AND coalesce(after->>'factory_contact_id', '') <> '')")


def downgrade():
    op.execute("LOCK TABLE factory_contacts, factory_price_approvals, audit_logs IN ACCESS EXCLUSIVE MODE")
    if op.get_bind().execute(sa.text("SELECT EXISTS (SELECT 1 FROM factory_contacts) "
                                    "OR EXISTS (SELECT 1 FROM audit_logs WHERE actor_user_id IS NULL)")).scalar():
        raise RuntimeError("Cannot discard factory authority or external decision history")
    op.drop_constraint("ck_audit_external_factory_actor", "audit_logs", type_="check")
    op.alter_column("audit_logs", "actor_user_id", nullable=False)
    op.drop_constraint("fk_factory_approvals_contact", "factory_price_approvals", type_="foreignkey")
    op.drop_column("factory_price_approvals", "factory_contact_id")
    op.drop_table("factory_contacts")
