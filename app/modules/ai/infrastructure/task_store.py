from __future__ import annotations

import hashlib
import json
import uuid
from datetime import timedelta

from sqlalchemy import select, text

from app.modules.ai.api.schemas import AiConversation, AiConversationPage, AiTask, AiTaskPage, AiTaskRequest
from app.modules.ai.infrastructure.models import AiAttemptORM, AiConversationORM, AiTaskORM
from app.modules.ai.infrastructure.proposal_store import ProposalStore
from app.modules.ai.infrastructure.provider import AiProviderError
from app.core.config import settings
from app.modules.ai.infrastructure.read_tools import load_actor
from app.modules.audit.application.service import AuditService
from app.shared.domain.errors import Conflict, ForbiddenScope, NotFound
from app.shared.infrastructure.db.base import utcnow


class TaskStore:
    """Short transactions only. Request locks never span a provider call."""

    def __init__(self, user, uow_factory, timeout_sec):
        self.user = user
        self.uow_factory = uow_factory
        self.timeout_sec = timeout_sec

    def _actor(self, uow):
        current = load_actor(uow, self.user)
        if current.admin_scope != self.user.admin_scope:
            raise ForbiddenScope("AI permissions changed")

    def _lock(self, uow):
        # Database-backed serialization across API workers; no process-local mutex.
        self._lock_internal(uow)
        self._actor(uow)

    def _owned(self, model):
        return select(model).where(model.company_id == self.user.company_id, model.owner_user_id == self.user.id)

    def _conversation(self, uow, conversation_id):
        row = uow.session.scalar(self._owned(AiConversationORM).where(AiConversationORM.id == conversation_id))
        if row is None or row.admin_scope != self.user.admin_scope:
            raise NotFound("AI conversation not found")
        return row

    def _task(self, uow, task_id):
        row = uow.session.scalar(self._owned(AiTaskORM).where(AiTaskORM.id == task_id))
        if row is None:
            raise NotFound("AI task not found")
        self._conversation(uow, row.conversation_id)
        self._expire(row)
        return row

    @staticmethod
    def _expire(row):
        if row.status == "RUNNING" and row.lease_expires_at <= utcnow():
            row.status = "INTERRUPTED"
            row.error_code = "AI_TASK_INTERRUPTED"
            row.updated_at = utcnow()

    def _view(self, row, uow=None):
        data = {name: getattr(row, name) for name in AiTask.model_fields if name != "proposals"}
        # Proposals are read live: their state changes after the task completes.
        data["proposals"] = ProposalStore(self.user, self.uow_factory, settings).list_for_task(uow, row.id) if uow is not None else []
        return AiTask.model_validate(data)

    @staticmethod
    def _fingerprint(body):
        return hashlib.sha256(json.dumps(body.model_dump(mode="json", exclude={"request_id"}),
            sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()

    def _existing(self, uow, body):
        key = uow.session.scalar(self._owned(AiAttemptORM).where(AiAttemptORM.request_id == body.request_id))
        if key is None:
            return None
        row = self._task(uow, key.task_id)
        if key.operation != "START" or row.request_fingerprint != self._fingerprint(body):
            raise Conflict("AI request ID was used for different input")
        return row

    def lookup(self, body):
        with self.uow_factory() as uow:
            self._lock(uow)
            row = self._existing(uow, body)
            return self._view(row, uow) if row else None

    def _idle(self, uow, conversation_id):
        running = uow.session.scalars(self._owned(AiTaskORM).where(
            AiTaskORM.conversation_id == conversation_id, AiTaskORM.status == "RUNNING")).all()
        for row in running:
            self._expire(row)
            if row.status == "RUNNING":
                raise Conflict("AI conversation already has a running task")
        uow.session.flush()

    def start(self, body: AiTaskRequest):
        with self.uow_factory() as uow:
            self._lock(uow)
            row = self._existing(uow, body)
            if row:
                return self._view(row, uow), None
            now = utcnow()
            if body.conversation_id:
                conversation = self._conversation(uow, body.conversation_id)
                self._idle(uow, conversation.id)
            else:
                conversation = AiConversationORM(id=uuid.uuid4(), company_id=self.user.company_id,
                    owner_user_id=self.user.id, admin_scope=self.user.admin_scope,
                    title=body.message[:120], created_at=now, updated_at=now)
                uow.session.add(conversation)
                uow.session.flush()
            row = AiTaskORM(id=uuid.uuid4(), company_id=self.user.company_id, owner_user_id=self.user.id,
                conversation_id=conversation.id, request_id=body.request_id, request_fingerprint=self._fingerprint(body),
                message=body.message, locale=body.locale, project_id=body.project_id,
                context=body.context.model_dump(mode="json") if body.context else None, status="RUNNING",
                attempt_id=uuid.uuid4(), attempt_count=1, lease_expires_at=now + timedelta(seconds=self.timeout_sec + 15),
                created_at=now, updated_at=now)
            uow.session.add(row)
            uow.session.flush()
            uow.session.add(AiAttemptORM(company_id=self.user.company_id, owner_user_id=self.user.id,
                request_id=body.request_id, task_id=row.id, operation="START"))
            conversation.updated_at = now
            return self._view(row, uow), row.attempt_id

    def retry(self, task_id, request_id):
        with self.uow_factory() as uow:
            self._lock(uow)
            row = self._task(uow, task_id)
            key = uow.session.scalar(self._owned(AiAttemptORM).where(AiAttemptORM.request_id == request_id))
            if key:
                if key.task_id != task_id or key.operation != "RETRY":
                    raise Conflict("AI request ID was already used")
                return self._view(row, uow), None
            if row.status == "COMPLETED":
                return self._view(row, uow), None
            if row.status not in {"FAILED", "INTERRUPTED"} or row.attempt_count >= 3:
                raise Conflict("AI task cannot be retried in its current state")
            latest = uow.session.scalar(self._owned(AiTaskORM).where(AiTaskORM.conversation_id == row.conversation_id)
                .order_by(AiTaskORM.created_at.desc(), AiTaskORM.id.desc()).limit(1))
            if latest.id != row.id:
                raise Conflict("Only the latest AI task can be retried")
            self._idle(uow, row.conversation_id)
            row.status = "RUNNING"
            row.error_code = None
            row.attempt_id = uuid.uuid4()
            row.attempt_count += 1
            row.lease_expires_at = utcnow() + timedelta(seconds=self.timeout_sec + 15)
            row.updated_at = utcnow()
            uow.session.add(AiAttemptORM(company_id=self.user.company_id, owner_user_id=self.user.id,
                request_id=request_id, task_id=row.id, operation="RETRY"))
            return self._view(row, uow), row.attempt_id

    def lookup_retry(self, task_id, request_id):
        with self.uow_factory() as uow:
            self._lock(uow)
            row = self._task(uow, task_id)
            key = uow.session.scalar(self._owned(AiAttemptORM).where(AiAttemptORM.request_id == request_id))
            if key and (key.task_id != task_id or key.operation != "RETRY"):
                raise Conflict("AI request ID was already used")
            return self._view(row, uow) if key or row.status == "COMPLETED" else None

    def get(self, task_id):
        with self.uow_factory() as uow:
            self._lock(uow)
            return self._view(self._task(uow, task_id), uow)

    def conversations(self, limit, offset):
        with self.uow_factory() as uow:
            self._actor(uow)
            rows = uow.session.scalars(self._owned(AiConversationORM).where(
                AiConversationORM.admin_scope == self.user.admin_scope).order_by(
                AiConversationORM.updated_at.desc(), AiConversationORM.id.desc()).offset(offset).limit(limit + 1)).all()
            return AiConversationPage(items=[AiConversation.model_validate({name: getattr(row, name)
                for name in AiConversation.model_fields}) for row in rows[:limit]], has_more=len(rows) > limit)

    def tasks(self, conversation_id, limit, offset):
        with self.uow_factory() as uow:
            self._lock(uow)
            self._conversation(uow, conversation_id)
            rows = uow.session.scalars(self._owned(AiTaskORM).where(AiTaskORM.conversation_id == conversation_id)
                .order_by(AiTaskORM.created_at.desc(), AiTaskORM.id.desc()).offset(offset).limit(limit + 1)).all()
            for row in rows:
                self._expire(row)
            return AiTaskPage(items=[self._view(row, uow) for row in rows[:limit]], has_more=len(rows) > limit)

    def history(self, task_id, attempt_id):
        with self.uow_factory() as uow:
            self._lock(uow)
            row = self._task(uow, task_id)
            self._running(row, attempt_id)
            rows = uow.session.scalars(self._owned(AiTaskORM).where(AiTaskORM.conversation_id == row.conversation_id,
                AiTaskORM.status == "COMPLETED", AiTaskORM.created_at < row.created_at)
                .order_by(AiTaskORM.created_at.desc(), AiTaskORM.id.desc()).limit(6)).all()
            history, size = [], 0
            for prior in rows:
                pair = [{"role": "user", "content": prior.message}, {"role": "assistant", "content": prior.reply["answer"]}]
                pair_size = sum(len(item["content"]) for item in pair)
                if size + pair_size > 24000:
                    break
                history[0:0] = pair
                size += pair_size
            return history

    @staticmethod
    def _running(row, attempt_id):
        if row.status != "RUNNING" or row.attempt_id != attempt_id:
            raise AiProviderError("AI_TASK_STOPPED")

    def check_running(self, task_id, attempt_id):
        with self.uow_factory() as uow:
            self._lock(uow)
            self._running(self._task(uow, task_id), attempt_id)

    def finish(self, task_id, attempt_id, reply, *, tools, provider_requests, duration_ms):
        with self.uow_factory() as uow:
            self._lock(uow)
            row = self._task(uow, task_id)
            # Cancellation/expired attempt wins over a late model response.
            if row.status == "RUNNING" and row.attempt_id == attempt_id:
                row.status = "COMPLETED"
                row.reply = reply.model_dump(mode="json")
                row.error_code = None
                row.updated_at = utcnow()
                self._conversation(uow, row.conversation_id).updated_at = row.updated_at
                self._audit(uow, row, tools, provider_requests, duration_ms)
            return self._view(row, uow)

    def fail(self, task_id, attempt_id, code, *, tools, provider_requests, duration_ms):
        # Internal finalization still records a failure after the actor lost access;
        # it never reads or returns conversation contents to that actor.
        with self.uow_factory() as uow:
            self._lock_internal(uow)
            row = uow.session.scalar(self._owned(AiTaskORM).where(AiTaskORM.id == task_id))
            if row:
                self._expire(row)
            if row and row.status == "RUNNING" and row.attempt_id == attempt_id:
                row.status = "FAILED"
                row.error_code = code
                row.updated_at = utcnow()
                self._audit(uow, row, tools, provider_requests, duration_ms)

    def _lock_internal(self, uow):
        key = int.from_bytes(hashlib.sha256(f"ai:{self.user.company_id}:{self.user.id}".encode()).digest()[:8], "big", signed=True)
        uow.session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})

    def _audit(self, uow, row, tools, provider_requests, duration_ms):
        AuditService.add(uow, company_id=self.user.company_id, actor_user_id=self.user.id,
            entity_type="AiRun", entity_id=row.id, action="AI_READ_QUERY", after={"status": row.status,
                "attempt_count": row.attempt_count, "tools": tools, "provider_requests": provider_requests,
                "duration_ms": duration_ms})

    def cancel(self, task_id):
        with self.uow_factory() as uow:
            self._lock(uow)
            row = self._task(uow, task_id)
            if row.status == "RUNNING":
                row.status = "CANCELLED"
                row.error_code = "AI_TASK_CANCELLED"
                row.updated_at = utcnow()
                AuditService.add(uow, company_id=self.user.company_id, actor_user_id=self.user.id,
                    entity_type="AiRun", entity_id=row.id, action="AI_TASK_CANCELLED",
                    after={"status": row.status, "attempt_count": row.attempt_count})
            return self._view(row, uow)
