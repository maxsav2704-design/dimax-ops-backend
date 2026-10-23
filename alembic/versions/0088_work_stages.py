"""Work stages: a company stage catalog, versioned stage plans per door type, a plan per door,
per-stage installer assignments with history, and immutable stage execution facts.

A door with a work plan is installed by completing its required stages, possibly by different
installers. Stage facts never create earnings here (step 4) and never unlock an installed door.

Revision ID: 0088_work_stages
Revises: 0087_commercial_agreements
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0088_work_stages"
down_revision = "0087_commercial_agreements"
branch_labels = None
depends_on = None

CODE = "code ~ '^[A-Z][A-Z0-9_]{0,39}$'"


def upgrade():
    op.create_table(
        "work_stage_definitions",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", pg.UUID(as_uuid=True), sa.ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("company_id", "code", name="uq_work_stage_code"),
        sa.CheckConstraint(CODE, name="ck_work_stage_code"),
        sa.CheckConstraint("btrim(name) <> ''", name="ck_work_stage_name"),
    )
    op.create_table(
        "door_type_stage_plans",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", pg.UUID(as_uuid=True), sa.ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("door_type_id", pg.UUID(as_uuid=True), sa.ForeignKey("door_types.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("created_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("company_id", "id", name="uq_door_type_stage_plan_tenant"),
        sa.UniqueConstraint("company_id", "door_type_id", "version", name="uq_door_type_stage_plan_version"),
        sa.CheckConstraint("version > 0 AND btrim(reason) <> ''", name="ck_door_type_stage_plan"),
    )
    op.create_table(
        "door_type_stage_plan_items",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("stage_code", sa.String(40), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["company_id", "plan_id"], ["door_type_stage_plans.company_id", "door_type_stage_plans.id"],
                                ondelete="RESTRICT", name="fk_stage_plan_item_plan"),
        sa.ForeignKeyConstraint(["company_id", "stage_code"], ["work_stage_definitions.company_id", "work_stage_definitions.code"],
                                ondelete="RESTRICT", name="fk_stage_plan_item_stage"),
        sa.UniqueConstraint("plan_id", "stage_code", name="uq_stage_plan_item_stage"),
        sa.UniqueConstraint("plan_id", "sequence", name="uq_stage_plan_item_sequence"),
    )
    op.create_table(
        "door_work_plans",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("door_id", pg.UUID(as_uuid=True), sa.ForeignKey("doors.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("plan_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("applied_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("replaced_at", sa.DateTime(timezone=True)),
        sa.Column("replaced_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT")),
        sa.ForeignKeyConstraint(["company_id", "plan_id"], ["door_type_stage_plans.company_id", "door_type_stage_plans.id"],
                                ondelete="RESTRICT", name="fk_door_work_plan_plan"),
        sa.CheckConstraint("(replaced_at IS NULL AND replaced_by IS NULL) OR (replaced_at IS NOT NULL AND replaced_by IS NOT NULL)",
                           name="ck_door_work_plan_replacement"),
    )
    op.create_index("uq_door_work_plan_current", "door_work_plans", ["door_id"], unique=True,
                    postgresql_where=sa.text("replaced_at IS NULL"))
    op.create_table(
        "door_stage_assignments",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("door_id", pg.UUID(as_uuid=True), sa.ForeignKey("doors.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("stage_code", sa.String(40), nullable=False),
        sa.Column("installer_id", pg.UUID(as_uuid=True), sa.ForeignKey("installers.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("assigned_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("replaced_at", sa.DateTime(timezone=True)),
        sa.Column("replaced_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT")),
        sa.ForeignKeyConstraint(["company_id", "stage_code"], ["work_stage_definitions.company_id", "work_stage_definitions.code"],
                                ondelete="RESTRICT", name="fk_door_stage_assignment_stage"),
        sa.CheckConstraint("(replaced_at IS NULL AND replaced_by IS NULL) OR (replaced_at IS NOT NULL AND replaced_by IS NOT NULL)",
                           name="ck_door_stage_assignment_replacement"),
    )
    op.create_index("uq_door_stage_assignment_current", "door_stage_assignments", ["door_id", "stage_code"], unique=True,
                    postgresql_where=sa.text("replaced_at IS NULL"))
    op.create_index("ix_door_stage_assignment_installer", "door_stage_assignments", ["company_id", "installer_id"])
    op.create_table(
        "door_stage_facts",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("door_id", pg.UUID(as_uuid=True), sa.ForeignKey("doors.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("stage_code", sa.String(40), nullable=False),
        sa.Column("plan_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("assignment_id", pg.UUID(as_uuid=True), sa.ForeignKey("door_stage_assignments.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("installer_id", pg.UUID(as_uuid=True), sa.ForeignKey("installers.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("happened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(24), nullable=False),
        sa.Column("client_event_id", sa.String(80)),
        sa.Column("request_id", pg.UUID(as_uuid=True)),
        sa.Column("created_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id", "plan_id"], ["door_type_stage_plans.company_id", "door_type_stage_plans.id"],
                                ondelete="RESTRICT", name="fk_door_stage_fact_plan"),
        sa.ForeignKeyConstraint(["company_id", "stage_code"], ["work_stage_definitions.company_id", "work_stage_definitions.code"],
                                ondelete="RESTRICT", name="fk_door_stage_fact_stage"),
        sa.UniqueConstraint("door_id", "stage_code", name="uq_door_stage_fact_once"),
        sa.CheckConstraint("happened_at <= received_at", name="ck_door_stage_fact_time"),
        sa.CheckConstraint("source IN ('API', 'ADMIN', 'OFFLINE_SYNC')", name="ck_door_stage_fact_source"),
    )
    op.create_index("uq_door_stage_fact_client_event", "door_stage_facts", ["company_id", "client_event_id"], unique=True,
                    postgresql_where=sa.text("client_event_id IS NOT NULL"))
    op.create_index("uq_door_stage_fact_request", "door_stage_facts", ["company_id", "request_id"], unique=True,
                    postgresql_where=sa.text("request_id IS NOT NULL"))
    op.execute("ALTER TYPE sync_event_type ADD VALUE IF NOT EXISTS 'DOOR_STAGE_COMPLETE'")
    op.execute("""
        CREATE FUNCTION guard_door_stage_fact() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Stage execution facts are immutable' USING ERRCODE = '23000';
        END; $$ LANGUAGE plpgsql;
        CREATE TRIGGER door_stage_fact_immutable BEFORE UPDATE OR DELETE ON door_stage_facts
            FOR EACH ROW EXECUTE FUNCTION guard_door_stage_fact();
    """)


def downgrade():
    op.execute("LOCK TABLE door_stage_facts IN ACCESS EXCLUSIVE MODE")
    if op.get_bind().execute(sa.text("SELECT EXISTS(SELECT 1 FROM door_stage_facts)")).scalar_one():
        raise RuntimeError("Cannot discard stage execution facts")
    op.execute("DROP TRIGGER door_stage_fact_immutable ON door_stage_facts")
    op.execute("DROP FUNCTION guard_door_stage_fact()")
    for name in ("door_stage_facts", "door_stage_assignments", "door_work_plans", "door_type_stage_plan_items",
                 "door_type_stage_plans", "work_stage_definitions"):
        op.drop_table(name)
    # The enum value DOOR_STAGE_COMPLETE stays: PostgreSQL cannot drop enum values in place.
