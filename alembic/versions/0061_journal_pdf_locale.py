"""Persist the language of journal PDFs without rewriting stored files."""
from alembic import op
import sqlalchemy as sa

revision = "0061_journal_pdf_locale"
down_revision = "0060_installer_journal_handoff"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("journals", sa.Column("pdf_locale", sa.String(2), nullable=False, server_default="en"))
    op.create_check_constraint("ck_journals_pdf_locale", "journals", "pdf_locale IN ('en', 'ru', 'he')")


def downgrade() -> None:
    op.drop_constraint("ck_journals_pdf_locale", "journals", type_="check")
    op.drop_column("journals", "pdf_locale")
