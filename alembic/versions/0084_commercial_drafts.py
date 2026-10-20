"""Separate commercial contract/price drafts from installer remuneration.

Revision ID: 0084_commercial_drafts
Revises: 0083_import_inbox
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0084_commercial_drafts"
down_revision = "0083_import_inbox"
branch_labels = None
depends_on = None


def _timestamps():
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade():
    op.create_table(
        "commercial_contracts",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", pg.UUID(as_uuid=True), sa.ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("factory_name", sa.String(200), nullable=False),
        sa.Column("reference", sa.String(200), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("is_demo", sa.Boolean(), nullable=False),
        sa.Column("request_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("created_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("company_id", "id", name="uq_commercial_contract_tenant"),
        sa.UniqueConstraint("company_id", "reference", name="uq_commercial_contract_reference"),
        sa.UniqueConstraint("company_id", "request_id", name="uq_commercial_contract_request"),
        sa.CheckConstraint("status = 'DRAFT' AND currency = 'ILS'", name="ck_commercial_contract_draft"),
        sa.CheckConstraint("btrim(factory_name) <> '' AND btrim(reference) <> '' AND btrim(reason) <> ''",
                           name="ck_commercial_contract_labels"),
    )
    op.create_table(
        "commercial_price_versions",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("contract_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("proposed_from", sa.Date(), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("agreement_reference", sa.String(200), nullable=False),
        sa.Column("request_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("created_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("company_id", "id", name="uq_commercial_price_tenant"),
        sa.ForeignKeyConstraint(["company_id", "contract_id"],
                                ["commercial_contracts.company_id", "commercial_contracts.id"],
                                ondelete="RESTRICT", name="fk_commercial_price_contract"),
        sa.UniqueConstraint("company_id", "contract_id", "version", name="uq_commercial_price_version"),
        sa.UniqueConstraint("company_id", "request_id", name="uq_commercial_price_request"),
        sa.CheckConstraint("version > 0 AND status = 'DRAFT'", name="ck_commercial_price_draft"),
        sa.CheckConstraint("btrim(reason) <> '' AND btrim(agreement_reference) <> ''",
                           name="ck_commercial_price_labels"),
    )
    op.create_table(
        "commercial_price_items",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("price_version_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("door_type_id", pg.UUID(as_uuid=True), sa.ForeignKey("door_types.id", ondelete="RESTRICT")),
        sa.Column("addon_type_id", pg.UUID(as_uuid=True), sa.ForeignKey("addon_types.id", ondelete="RESTRICT")),
        sa.Column("stage_code", sa.String(40), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("unit", sa.String(20), nullable=False),
        sa.Column("unit_price_ex_vat", sa.Numeric(12, 2), nullable=False),
        sa.ForeignKeyConstraint(["company_id", "price_version_id"],
                                ["commercial_price_versions.company_id", "commercial_price_versions.id"],
                                ondelete="RESTRICT", name="fk_commercial_item_version"),
        sa.UniqueConstraint("price_version_id", "kind", "door_type_id", "stage_code",
                            name="uq_commercial_item_door_stage"),
        sa.UniqueConstraint("price_version_id", "addon_type_id", name="uq_commercial_item_addon"),
        sa.CheckConstraint(
            "(kind = 'INSTALLATION' AND door_type_id IS NOT NULL AND addon_type_id IS NULL AND stage_code = '') OR "
            "(kind = 'STAGE' AND door_type_id IS NOT NULL AND addon_type_id IS NULL "
            "AND stage_code ~ '^[A-Z][A-Z0-9_]{0,39}$') OR "
            "(kind = 'ADDON' AND door_type_id IS NULL AND addon_type_id IS NOT NULL AND stage_code = '')",
            name="ck_commercial_item_target",
        ),
        sa.CheckConstraint("unit_price_ex_vat >= 0 AND unit_price_ex_vat < 10000000000",
                           name="ck_commercial_item_price"),
        sa.CheckConstraint("btrim(name) <> '' AND btrim(unit) <> ''", name="ck_commercial_item_labels"),
    )


def downgrade():
    op.drop_table("commercial_price_items")
    op.drop_table("commercial_price_versions")
    op.drop_table("commercial_contracts")
