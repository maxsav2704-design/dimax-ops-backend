"""Indexes for the door completion and webhook lookups used on every sync.

completed_work.door_id is read on every door completion and reversal
(doors/application/completion.py); outbox_messages.provider_message_id is the
webhook delivery lookup key. Neither column had an index. No data changes.
"""
from alembic import op

revision = "0075_sync_hot_path_indexes"
down_revision = "0074_work_price_accruals"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("ix_completed_work_door_id", "completed_work", ["door_id"])
    op.create_index("ix_outbox_provider_message_id", "outbox_messages", ["provider_message_id"])


def downgrade():
    op.drop_index("ix_outbox_provider_message_id", table_name="outbox_messages")
    op.drop_index("ix_completed_work_door_id", table_name="completed_work")
