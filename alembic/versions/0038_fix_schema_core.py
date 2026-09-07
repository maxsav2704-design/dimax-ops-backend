"""Fix schema core: add missing columns to existing tables per TZ.

projects: lifecycle_status, health_status
doors: door_code, is_critical, version, surcharge_pct, apply_surcharge_to_installer
door_types: is_critical_default
issues: created_by_user_id

Revision ID: 0038_fix_schema_core
Revises: 0037_missing_tables
Create Date: 2026-03-31 10:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID


revision = "0038_fix_schema_core"
down_revision = "0037_missing_tables"
branch_labels = None
depends_on = None


def _table_columns(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table_name)}


def _index_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {index["name"] for index in inspector.get_indexes(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    project_columns = _table_columns(inspector, "projects")
    project_indexes = _index_names(inspector, "projects")
    if "lifecycle_status" not in project_columns:
        op.add_column(
            "projects",
            sa.Column(
                "lifecycle_status",
                sa.String(20),
                nullable=False,
                server_default="ACTIVE",
            ),
        )
    if "health_status" not in project_columns:
        op.add_column(
            "projects",
            sa.Column(
                "health_status",
                sa.String(20),
                nullable=False,
                server_default="NORMAL",
            ),
        )
    op.execute(
        """
        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'ck_projects_lifecycle_status'
          ) THEN
            ALTER TABLE projects
              ADD CONSTRAINT ck_projects_lifecycle_status
              CHECK (lifecycle_status IN ('PLANNED', 'ACTIVE', 'COMPLETED', 'ARCHIVED'));
          END IF;
          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'ck_projects_health_status'
          ) THEN
            ALTER TABLE projects
              ADD CONSTRAINT ck_projects_health_status
              CHECK (health_status IN ('NORMAL', 'AT_RISK', 'BLOCKED'));
          END IF;
        END $$;
        """
    )
    if "ix_projects_lifecycle_status" not in project_indexes:
        op.create_index("ix_projects_lifecycle_status", "projects", ["lifecycle_status"])
    if "ix_projects_health_status" not in project_indexes:
        op.create_index("ix_projects_health_status", "projects", ["health_status"])

    door_columns = _table_columns(inspector, "doors")
    if "door_code" not in door_columns:
        op.add_column("doors", sa.Column("door_code", sa.String(120), nullable=True))
    if "is_critical" not in door_columns:
        op.add_column(
            "doors",
            sa.Column(
                "is_critical",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )
    if "version" not in door_columns:
        op.add_column(
            "doors",
            sa.Column(
                "version",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )
    if "surcharge_pct" not in door_columns:
        op.add_column(
            "doors",
            sa.Column(
                "surcharge_pct",
                sa.Numeric(6, 2),
                nullable=False,
                server_default=sa.text("100.00"),
            ),
        )
    if "apply_surcharge_to_installer" not in door_columns:
        op.add_column(
            "doors",
            sa.Column(
                "apply_surcharge_to_installer",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )
    op.execute(
        """
        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'uq_doors_project_door_code'
          ) THEN
            ALTER TABLE doors
              ADD CONSTRAINT uq_doors_project_door_code
              UNIQUE (project_id, door_code);
          END IF;
          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'ck_doors_surcharge_pct'
          ) THEN
            ALTER TABLE doors
              ADD CONSTRAINT ck_doors_surcharge_pct
              CHECK (surcharge_pct >= 100);
          END IF;
        END $$;
        """
    )

    door_type_columns = _table_columns(inspector, "door_types")
    if "is_critical_default" not in door_type_columns:
        op.add_column(
            "door_types",
            sa.Column(
                "is_critical_default",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )

    issue_columns = _table_columns(inspector, "issues")
    issue_indexes = _index_names(inspector, "issues")
    if "created_by_user_id" not in issue_columns:
        op.add_column(
            "issues",
            sa.Column(
                "created_by_user_id",
                UUID(as_uuid=True),
                nullable=True,
            ),
        )
    op.execute(
        """
        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'fk_issues_created_by_user_id_users'
          ) AND NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'issues_created_by_user_id_fkey'
          ) THEN
            ALTER TABLE issues
              ADD CONSTRAINT fk_issues_created_by_user_id_users
              FOREIGN KEY (created_by_user_id)
              REFERENCES users(id)
              ON DELETE SET NULL;
          END IF;
        END $$;
        """
    )
    if "ix_issues_created_by_user_id" not in issue_indexes:
        op.create_index("ix_issues_created_by_user_id", "issues", ["created_by_user_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    issue_columns = _table_columns(inspector, "issues")
    issue_indexes = _index_names(inspector, "issues")
    if "ix_issues_created_by_user_id" in issue_indexes:
        op.drop_index("ix_issues_created_by_user_id", table_name="issues")
    if "created_by_user_id" in issue_columns:
        op.execute(
            """
            DO $$
            BEGIN
              IF EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_issues_created_by_user_id_users'
              ) THEN
                ALTER TABLE issues DROP CONSTRAINT fk_issues_created_by_user_id_users;
              END IF;
              IF EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'issues_created_by_user_id_fkey'
              ) THEN
                ALTER TABLE issues DROP CONSTRAINT issues_created_by_user_id_fkey;
              END IF;
            END $$;
            """
        )
        op.drop_column("issues", "created_by_user_id")

    door_type_columns = _table_columns(inspector, "door_types")
    if "is_critical_default" in door_type_columns:
        op.drop_column("door_types", "is_critical_default")

    door_columns = _table_columns(inspector, "doors")
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'ck_doors_surcharge_pct'
          ) THEN
            ALTER TABLE doors DROP CONSTRAINT ck_doors_surcharge_pct;
          END IF;
          IF EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'uq_doors_project_door_code'
          ) THEN
            ALTER TABLE doors DROP CONSTRAINT uq_doors_project_door_code;
          END IF;
        END $$;
        """
    )
    for column_name in [
        "apply_surcharge_to_installer",
        "surcharge_pct",
        "version",
        "is_critical",
        "door_code",
    ]:
        if column_name in door_columns:
            op.drop_column("doors", column_name)

    project_columns = _table_columns(inspector, "projects")
    project_indexes = _index_names(inspector, "projects")
    if "ix_projects_health_status" in project_indexes:
        op.drop_index("ix_projects_health_status", table_name="projects")
    if "ix_projects_lifecycle_status" in project_indexes:
        op.drop_index("ix_projects_lifecycle_status", table_name="projects")
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'ck_projects_health_status'
          ) THEN
            ALTER TABLE projects DROP CONSTRAINT ck_projects_health_status;
          END IF;
          IF EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'ck_projects_lifecycle_status'
          ) THEN
            ALTER TABLE projects DROP CONSTRAINT ck_projects_lifecycle_status;
          END IF;
        END $$;
        """
    )
    if "health_status" in project_columns:
        op.drop_column("projects", "health_status")
    if "lifecycle_status" in project_columns:
        op.drop_column("projects", "lifecycle_status")
