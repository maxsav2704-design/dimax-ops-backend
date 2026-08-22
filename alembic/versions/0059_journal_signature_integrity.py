"""Enforce one immutable signature per journal.

Revision ID: 0059_journal_signature_integrity
Revises: 0058_file_token_usage_integrity
Create Date: 2026-08-24

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0059_journal_signature_integrity"
down_revision = "0058_file_token_usage_integrity"
branch_labels = None
depends_on = None


CONSTRAINT_NAME = "uq_journal_signatures_one_per_journal"


def _unique_constraint_names() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("journal_signatures")
        if constraint.get("name")
    }


def _assert_no_duplicate_signatures() -> None:
    duplicate = op.get_bind().execute(
        sa.text(
            """
            SELECT journal_id, COUNT(*) AS signature_count
            FROM journal_signatures
            GROUP BY journal_id
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        )
    ).first()
    if duplicate is not None:
        raise RuntimeError(
            "Cannot enforce one signature per journal: journal "
            f"{duplicate.journal_id} has {duplicate.signature_count} signatures "
            "and requires manual review"
        )


def upgrade() -> None:
    _assert_no_duplicate_signatures()
    if CONSTRAINT_NAME not in _unique_constraint_names():
        op.create_unique_constraint(
            CONSTRAINT_NAME,
            "journal_signatures",
            ["journal_id"],
        )


def downgrade() -> None:
    if CONSTRAINT_NAME in _unique_constraint_names():
        op.drop_constraint(
            CONSTRAINT_NAME,
            "journal_signatures",
            type_="unique",
        )
