"""Constrain project lifecycle and derived health statuses.

Revision ID: 0055_project_operational_status
Revises: 0054_sync_issue_create_event
Create Date: 2026-07-16

"""
from __future__ import annotations

from alembic import op


revision = "0055_project_operational_status"
down_revision = "0054_sync_issue_create_event"
branch_labels = None
depends_on = None


LIFECYCLE_VALUES = ("PLANNED", "ACTIVE", "ON_HOLD", "COMPLETED", "CANCELLED")
HEALTH_VALUES = ("NORMAL", "AT_RISK", "BLOCKED")


def upgrade() -> None:
    op.execute(
        """
        UPDATE projects
        SET lifecycle_status = 'ACTIVE'
        WHERE lifecycle_status IS NULL
           OR lifecycle_status NOT IN (
               'PLANNED', 'ACTIVE', 'ON_HOLD', 'COMPLETED', 'CANCELLED'
           )
        """
    )
    op.execute(
        """
        UPDATE projects
        SET health_status = CASE
            WHEN health_status = 'OK' THEN 'NORMAL'
            WHEN health_status IN ('DANGER', 'ERROR') THEN 'BLOCKED'
            WHEN health_status IN ('WARNING', 'WARN') THEN 'AT_RISK'
            WHEN status::text = 'PROBLEM' THEN 'BLOCKED'
            ELSE 'NORMAL'
        END
        WHERE health_status IS NULL
           OR health_status NOT IN ('NORMAL', 'AT_RISK', 'BLOCKED')
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'ck_projects_lifecycle_status'
                  AND conrelid = 'projects'::regclass
            ) THEN
                ALTER TABLE projects
                ADD CONSTRAINT ck_projects_lifecycle_status
                CHECK (lifecycle_status IN (
                    'PLANNED', 'ACTIVE', 'ON_HOLD', 'COMPLETED', 'CANCELLED'
                ));
            END IF;
        END
        $$
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'ck_projects_health_status'
                  AND conrelid = 'projects'::regclass
            ) THEN
                ALTER TABLE projects
                ADD CONSTRAINT ck_projects_health_status
                CHECK (health_status IN ('NORMAL', 'AT_RISK', 'BLOCKED'));
            END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE projects DROP CONSTRAINT IF EXISTS ck_projects_health_status"
    )
    op.execute(
        "ALTER TABLE projects DROP CONSTRAINT IF EXISTS ck_projects_lifecycle_status"
    )
