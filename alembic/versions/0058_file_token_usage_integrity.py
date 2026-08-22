"""Make public file-token usage atomic and non-negative.

Revision ID: 0058_file_token_usage_integrity
Revises: 0057_payroll_correction_uq
Create Date: 2026-08-24

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0058_file_token_usage_integrity"
down_revision = "0057_payroll_correction_uq"
branch_labels = None
depends_on = None


CONSTRAINT_NAME = "ck_file_download_tokens_uses_left_non_negative"


def _check_names() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {
        constraint["name"]
        for constraint in inspector.get_check_constraints("file_download_tokens")
        if constraint.get("name")
    }


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE file_download_tokens SET uses_left = 0 WHERE uses_left < 0"
        )
    )
    if CONSTRAINT_NAME not in _check_names():
        op.create_check_constraint(
            CONSTRAINT_NAME,
            "file_download_tokens",
            "uses_left >= 0",
        )


def downgrade() -> None:
    if CONSTRAINT_NAME in _check_names():
        op.drop_constraint(
            CONSTRAINT_NAME,
            "file_download_tokens",
            type_="check",
        )
