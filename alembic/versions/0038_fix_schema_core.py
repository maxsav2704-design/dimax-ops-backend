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


def upgrade() -> None:
    # ── projects ────────────────────────────────────────────────────────────
    op.add_column(
        "projects",
        sa.Column(
            "lifecycle_status",
            sa.String(20),
            nullable=False,
            server_default="ACTIVE",
        ),
    )
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
    op.create_index("ix_projects_lifecycle_status", "projects", ["lifecycle_status"])
    op.create_index("ix_projects_health_status", "projects", ["health_status"])

    # ── doors ───────────────────────────────────────────────────────────────
    op.add_column(
        "doors",
        sa.Column("door_code", sa.String(120), nullable=True),
    )
    op.add_column(
        "doors",
        sa.Column(
            "is_critical",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "doors",
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "doors",
        sa.Column(
            "surcharge_pct",
            sa.Numeric(6, 2),
            nullable=False,
            server_default=sa.text("100.00"),
        ),
    )
    op.add_column(
        "doors",
        sa.Column(
            "apply_surcharge_to_installer",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    # Unique constraint on (project_id, door_code) — guard against duplicates
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

    # ── door_types ──────────────────────────────────────────────────────────
    op.add_column(
        "door_types",
        sa.Column(
            "is_critical_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # ── issues ──────────────────────────────────────────────────────────────
    # owner_user_id, due_at, priority, workflow_state were added in 0027.
    # Only created_by_user_id is missing.
    op.add_column(
        "issues",
        sa.Column(
            "created_by_user_id",
            UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_issues_created_by_user_id_users",
        "issues",
        "users",
        ["created_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_issues_created_by_user_id", "issues", ["created_by_user_id"])


def downgrade() -> None:
    # issues
    op.drop_index("ix_issues_created_by_user_id", table_name="issues")
    op.drop_constraint("fk_issues_created_by_user_id_users", "issues", type_="foreignkey")
    op.drop_column("issues", "created_by_user_id")

    # door_types
    op.drop_column("door_types", "is_critical_default")

    # doors
    op.drop_constraint("ck_doors_surcharge_pct", "doors", type_="check")
    op.drop_constraint("uq_doors_project_door_code", "doors", type_="unique")
    op.drop_column("doors", "apply_surcharge_to_installer")
    op.drop_column("doors", "surcharge_pct")
    op.drop_column("doors", "version")
    op.drop_column("doors", "is_critical")
    op.drop_column("doors", "door_code")

    # projects
    op.drop_index("ix_projects_health_status", table_name="projects")
    op.drop_index("ix_projects_lifecycle_status", table_name="projects")
    op.drop_constraint("ck_projects_health_status", "projects", type_="check")
    op.drop_constraint("ck_projects_lifecycle_status", "projects", type_="check")
    op.drop_column("projects", "health_status")
    op.drop_column("projects", "lifecycle_status")
