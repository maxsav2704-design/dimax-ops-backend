from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.infrastructure.db.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class AiConversationORM(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    __tablename__ = "ai_conversations"
    __table_args__ = (
        UniqueConstraint("company_id", "owner_user_id", "id", name="uq_ai_conversation_owner"),
        CheckConstraint("owner_role IN ('ADMIN','INSTALLER')", name="ck_ai_conversation_owner_role"),
        Index("ix_ai_conversation_owner_updated", "company_id", "owner_user_id", "updated_at"),
    )
    owner_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    # Admin scope of the owner (None for installers); a scope or role change hides the old history (0080).
    admin_scope: Mapped[str | None] = mapped_column(String(20))
    owner_role: Mapped[str] = mapped_column(String(16), default="ADMIN", server_default="ADMIN")
    title: Mapped[str] = mapped_column(String(120))


class AiTaskORM(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    __tablename__ = "ai_tasks"
    __table_args__ = (
        UniqueConstraint("company_id", "owner_user_id", "id", name="uq_ai_task_owner"),
        UniqueConstraint("company_id", "owner_user_id", "request_id", name="uq_ai_task_request"),
        ForeignKeyConstraint(["company_id", "owner_user_id", "conversation_id"],
            ["ai_conversations.company_id", "ai_conversations.owner_user_id", "ai_conversations.id"],
            ondelete="CASCADE", name="fk_ai_task_conversation_owner"),
        CheckConstraint("status IN ('RUNNING','COMPLETED','FAILED','INTERRUPTED','CANCELLED')", name="ck_ai_task_status"),
        CheckConstraint("attempt_count BETWEEN 1 AND 3", name="ck_ai_task_attempt_count"),
        Index("ix_ai_task_conversation_created", "company_id", "conversation_id", "created_at"),
        Index("uq_ai_task_running_conversation", "conversation_id", unique=True,
              postgresql_where=text("status = 'RUNNING'")),
    )
    owner_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text)
    locale: Mapped[str] = mapped_column(String(2))
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(16))
    attempt_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    attempt_count: Mapped[int] = mapped_column(Integer)
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reply: Mapped[dict | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(64))
    # Selected object the question was asked about ({"kind": "project|door|issue", "id": ...}), migration 0079.
    context: Mapped[dict | None] = mapped_column(JSONB)


class AiAttemptORM(Base, TenantMixin):
    __tablename__ = "ai_task_attempts"
    __table_args__ = (
        ForeignKeyConstraint(["company_id", "owner_user_id", "task_id"],
            ["ai_tasks.company_id", "ai_tasks.owner_user_id", "ai_tasks.id"],
            ondelete="CASCADE", name="fk_ai_attempt_task_owner"),
    )
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, index=True)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    operation: Mapped[str] = mapped_column(String(8))


class AiProposalORM(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    """A business action prepared by the agent; executed only by an explicit admin confirmation (0079)."""

    __tablename__ = "ai_proposals"
    __table_args__ = (
        ForeignKeyConstraint(["company_id", "owner_user_id", "task_id"],
            ["ai_tasks.company_id", "ai_tasks.owner_user_id", "ai_tasks.id"],
            ondelete="CASCADE", name="fk_ai_proposal_task_owner"),
        CheckConstraint("status IN ('PROPOSED','CONFIRMED','EXECUTED','REJECTED','EXPIRED','FAILED','CONFLICT')",
                        name="ck_ai_proposal_status"),
        Index("ix_ai_proposal_task", "company_id", "task_id"),
    )
    owner_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    tool_name: Mapped[str] = mapped_column(String(40))
    arguments: Mapped[dict] = mapped_column(JSONB)
    preview: Mapped[dict] = mapped_column(JSONB)
    expected: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16))
    confirm_request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    result: Mapped[dict | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
