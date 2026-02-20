"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-02-13

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- ENUM TYPES (PostgreSQL) ---
    # create_type=False so SQLAlchemy won't try to re-create inside create_table()
    user_role = postgresql.ENUM("ADMIN", "INSTALLER", name="user_role", create_type=False)
    project_status = postgresql.ENUM("OK", "PROBLEM", name="project_status", create_type=False)
    door_status = postgresql.ENUM("INSTALLED", "NOT_INSTALLED", name="door_status", create_type=False)
    issue_status = postgresql.ENUM("OPEN", "CLOSED", name="issue_status", create_type=False)

    user_role.create(op.get_bind(), checkfirst=True)
    project_status.create(op.get_bind(), checkfirst=True)
    door_status.create(op.get_bind(), checkfirst=True)
    issue_status.create(op.get_bind(), checkfirst=True)

    # --- companies ---
    op.create_table(
        "companies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )

    # --- users ---
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("role", user_role, nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("company_id", "email", name="uq_users_company_email"),
    )
    op.create_index("ix_users_company_id", "users", ["company_id"])
    op.create_index("ix_users_email", "users", ["email"])

    # --- auth_refresh_tokens ---
    op.create_table(
        "auth_refresh_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("jti", sa.String(length=64), nullable=False),
        sa.Column("token_hash", sa.String(length=255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by_jti", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("company_id", "jti", name="uq_auth_refresh_tokens_company_jti"),
    )
    op.create_index("ix_auth_refresh_tokens_user", "auth_refresh_tokens", ["company_id", "user_id"])

    # --- audit_logs ---
    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_type", sa.String(length=80), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
    )
    op.create_index("ix_audit_logs_company_id", "audit_logs", ["company_id"])
    op.create_index("ix_audit_logs_actor_user_id", "audit_logs", ["actor_user_id"])
    op.create_index("ix_audit_logs_entity_id", "audit_logs", ["entity_id"])

    # --- door_types ---
    op.create_table(
        "door_types",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.UniqueConstraint("company_id", "code", name="uq_door_types_company_code"),
    )
    op.create_index("ix_door_types_company_id", "door_types", ["company_id"])
    op.create_index("ix_door_types_code", "door_types", ["code"])

    # --- reasons ---
    op.create_table(
        "reasons",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.UniqueConstraint("company_id", "code", name="uq_reasons_company_code"),
    )
    op.create_index("ix_reasons_company_id", "reasons", ["company_id"])
    op.create_index("ix_reasons_code", "reasons", ["code"])

    # --- installers ---
    op.create_table(
        "installers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("phone", sa.String(length=40), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("address", sa.String(length=500), nullable=True),
        sa.Column("passport_id", sa.String(length=80), nullable=True),
        sa.Column("notes", sa.String(length=1000), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'ACTIVE'")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.UniqueConstraint("company_id", "phone", name="uq_installers_company_phone"),
    )
    op.create_index("ix_installers_company_id", "installers", ["company_id"])
    op.create_index("ix_installers_user_id", "installers", ["user_id"])

    # --- installer_rates ---
    op.create_table(
        "installer_rates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("installer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("door_type_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("price", sa.Numeric(12, 2), nullable=False),
        sa.CheckConstraint("price >= 0", name="ck_rates_price_nonnegative"),
        sa.UniqueConstraint(
            "company_id", "installer_id", "door_type_id",
            name="uq_rates_installer_door_type",
        ),
        sa.ForeignKeyConstraint(["installer_id"], ["installers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["door_type_id"], ["door_types.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_installer_rates_company_id", "installer_rates", ["company_id"])
    op.create_index("ix_installer_rates_installer_id", "installer_rates", ["installer_id"])
    op.create_index("ix_installer_rates_door_type_id", "installer_rates", ["door_type_id"])

    # --- projects ---
    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("address", sa.String(length=400), nullable=False),
        sa.Column("developer_company", sa.String(length=200), nullable=True),
        sa.Column("contact_name", sa.String(length=200), nullable=True),
        sa.Column("contact_phone", sa.String(length=40), nullable=True),
        sa.Column("contact_email", sa.String(length=255), nullable=True),
        sa.Column("status", project_status, nullable=False, server_default=sa.text("'OK'")),
        sa.UniqueConstraint(
            "company_id", "name", "address",
            name="uq_projects_company_name_address",
        ),
    )
    op.create_index("ix_projects_company_id", "projects", ["company_id"])
    op.create_index("ix_projects_status", "projects", ["status"])

    # --- doors ---
    op.create_table(
        "doors",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("door_type_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("unit_label", sa.String(length=120), nullable=False),
        sa.Column("our_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("status", door_status, nullable=False, server_default=sa.text("'NOT_INSTALLED'")),
        sa.Column("installer_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reason_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("comment", sa.String(length=1000), nullable=True),
        sa.Column("installed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_locked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.CheckConstraint("our_price >= 0", name="ck_doors_our_price_nonnegative"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["door_type_id"], ["door_types.id"]),
        sa.ForeignKeyConstraint(["installer_id"], ["installers.id"]),
        sa.ForeignKeyConstraint(["reason_id"], ["reasons.id"]),
        sa.UniqueConstraint(
            "company_id", "project_id", "unit_label", "door_type_id",
            name="uq_doors_project_unit_type",
        ),
    )
    op.create_index("ix_doors_company_id", "doors", ["company_id"])
    op.create_index("ix_doors_project_id", "doors", ["project_id"])
    op.create_index("ix_doors_project_status", "doors", ["project_id", "status"])
    op.create_index("ix_doors_door_type_id", "doors", ["door_type_id"])
    op.create_index("ix_doors_installer_id", "doors", ["installer_id"])
    op.create_index("ix_doors_reason_id", "doors", ["reason_id"])

    # --- issues ---
    op.create_table(
        "issues",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("door_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", issue_status, nullable=False, server_default=sa.text("'OPEN'")),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("details", sa.String(length=2000), nullable=True),
        sa.ForeignKeyConstraint(["door_id"], ["doors.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("company_id", "door_id", name="uq_issues_company_door"),
    )
    op.create_index("ix_issues_company_id", "issues", ["company_id"])
    op.create_index("ix_issues_door_id", "issues", ["door_id"])
    op.create_index("ix_issues_status", "issues", ["status"])


def downgrade() -> None:
    op.drop_table("issues")
    op.drop_table("doors")
    op.drop_table("projects")
    op.drop_table("installer_rates")
    op.drop_table("installers")
    op.drop_table("reasons")
    op.drop_table("door_types")
    op.drop_table("audit_logs")
    op.drop_table("auth_refresh_tokens")
    op.drop_table("users")
    op.drop_table("companies")

    # drop enums last
    postgresql.ENUM("OPEN", "CLOSED", name="issue_status").drop(
        op.get_bind(), checkfirst=True
    )
    postgresql.ENUM("INSTALLED", "NOT_INSTALLED", name="door_status").drop(
        op.get_bind(), checkfirst=True
    )
    postgresql.ENUM("OK", "PROBLEM", name="project_status").drop(
        op.get_bind(), checkfirst=True
    )
    postgresql.ENUM("ADMIN", "INSTALLER", name="user_role").drop(
        op.get_bind(), checkfirst=True
    )
