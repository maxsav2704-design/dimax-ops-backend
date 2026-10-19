"""DIMAX AI for installers: conversations belong to any active user of the company.

0068 bound AI conversations to admin profiles (composite FK) and required an
admin scope. Installers now own conversations too: the FK moves to users (it
already existed as a plain FK), the scope becomes nullable and the owner's role
is stored so that a role change hides the old history, like a scope change does.

Revision ID: 0080_ai_installers
Revises: 0079_ai_proposals
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0080_ai_installers"
down_revision = "0079_ai_proposals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("fk_ai_conversation_admin_owner", "ai_conversations", type_="foreignkey")
    op.alter_column("ai_conversations", "admin_scope", existing_type=sa.String(20), nullable=True)
    op.add_column("ai_conversations", sa.Column("owner_role", sa.String(16), nullable=False, server_default="ADMIN"))
    op.create_check_constraint("ck_ai_conversation_owner_role", "ai_conversations", "owner_role IN ('ADMIN','INSTALLER')")


def downgrade() -> None:
    op.execute("DELETE FROM ai_conversations WHERE owner_role <> 'ADMIN'")
    op.drop_constraint("ck_ai_conversation_owner_role", "ai_conversations", type_="check")
    op.drop_column("ai_conversations", "owner_role")
    op.alter_column("ai_conversations", "admin_scope", existing_type=sa.String(20), nullable=False)
    op.create_foreign_key("fk_ai_conversation_admin_owner", "ai_conversations", "admin_profiles",
                          ["company_id", "owner_user_id"], ["company_id", "user_id"], ondelete="CASCADE")
