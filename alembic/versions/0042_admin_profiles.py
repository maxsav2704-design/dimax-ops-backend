"""Create admin_profiles persistence table.

Revision ID: 0042_admin_profiles
Revises: 0041_refresh_sessions_metadata
Create Date: 2026-04-02 15:20:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0042_admin_profiles"
down_revision = "0041_refresh_sessions_metadata"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _constraint_names(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    names: set[str] = set()
    for item in inspector.get_unique_constraints(table_name):
        if item.get("name"):
            names.add(str(item["name"]))
    for item in inspector.get_check_constraints(table_name):
        if item.get("name"):
            names.add(str(item["name"]))
    for item in inspector.get_foreign_keys(table_name):
        if item.get("name"):
            names.add(str(item["name"]))
    return names


def _index_names(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {
        str(item["name"])
        for item in inspector.get_indexes(table_name)
        if item.get("name")
    }


def upgrade() -> None:
    if not _has_table("admin_profiles"):
        op.create_table(
            "admin_profiles",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("company_id", sa.UUID(), nullable=False),
            sa.Column("user_id", sa.UUID(), nullable=False),
            sa.Column("admin_scope", sa.String(length=20), nullable=False),
            sa.Column(
                "can_view_rates",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column(
                "can_manage_imports",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column(
                "can_manage_users",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.ForeignKeyConstraint(
                ["company_id"], ["companies.id"], ondelete="CASCADE", name="fk_admin_profiles_company_id_companies"
            ),
            sa.ForeignKeyConstraint(
                ["user_id"], ["users.id"], ondelete="CASCADE", name="fk_admin_profiles_user_id_users"
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    constraints = _constraint_names("admin_profiles")
    indexes = _index_names("admin_profiles")

    if "uq_admin_profiles_company_user" not in constraints:
        op.create_unique_constraint(
            "uq_admin_profiles_company_user",
            "admin_profiles",
            ["company_id", "user_id"],
        )

    if "ck_admin_profiles_scope" not in constraints:
        op.create_check_constraint(
            "ck_admin_profiles_scope",
            "admin_profiles",
            "admin_scope IN ('OWNER','OPERATIONS','FINANCE','VIEWER')",
        )

    if "ix_admin_profiles_company_scope" not in indexes:
        op.create_index(
            "ix_admin_profiles_company_scope",
            "admin_profiles",
            ["company_id", "admin_scope"],
        )


def downgrade() -> None:
    if not _has_table("admin_profiles"):
        return

    indexes = _index_names("admin_profiles")
    constraints = _constraint_names("admin_profiles")

    if "ix_admin_profiles_company_scope" in indexes:
        op.drop_index("ix_admin_profiles_company_scope", table_name="admin_profiles")
    if "uq_admin_profiles_company_user" in constraints:
        op.drop_constraint(
            "uq_admin_profiles_company_user",
            "admin_profiles",
            type_="unique",
        )
    if "ck_admin_profiles_scope" in constraints:
        op.drop_constraint("ck_admin_profiles_scope", "admin_profiles", type_="check")

    op.drop_table("admin_profiles")
