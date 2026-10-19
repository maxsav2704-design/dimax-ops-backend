"""DIMAX AI worker: executes queued agent tasks outside the HTTP request.

With AI_EXECUTION_MODE=background the API only records the task (RUNNING, unclaimed)
and answers at once; the web and mobile clients already poll the task. This worker
claims one unclaimed task at a time with SELECT ... FOR UPDATE SKIP LOCKED (several
workers never run the same attempt), gives it a fresh lease and runs exactly the same
pipeline as the inline path: live actor re-read, tools, proposals, finish/fail with
metadata audit. A worker that dies leaves the lease to expire; the client sees
INTERRUPTED and may retry explicitly (a retry clears the claim).
"""
from __future__ import annotations

import time
from datetime import timedelta

from sqlalchemy import select

from app.api.v1.deps import CurrentUser
from app.core.config import settings
from app.modules.ai.api.routes import execute_task
from app.modules.ai.api.schemas import AiTask
from app.modules.ai.infrastructure.models import AiConversationORM, AiTaskORM
from app.modules.ai.infrastructure.task_store import TaskStore
from app.shared.domain.errors import Forbidden
from app.shared.infrastructure.db.base import utcnow
from app.shared.infrastructure.db.session import SessionLocal
from app.shared.infrastructure.db.uow_sqlalchemy import SqlAlchemyUnitOfWork


def claim_next() -> tuple[AiTask, object, CurrentUser] | None:
    """Claim the oldest unclaimed RUNNING task whose lease is still valid."""
    session = SessionLocal()
    try:
        now = utcnow()
        row = session.execute(
            select(AiTaskORM)
            .where(AiTaskORM.status == "RUNNING", AiTaskORM.claimed_at.is_(None), AiTaskORM.lease_expires_at > now)
            .order_by(AiTaskORM.created_at, AiTaskORM.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        ).scalar_one_or_none()
        if row is None:
            return None
        conversation = session.get(AiConversationORM, row.conversation_id)
        row.claimed_at = now
        # The execution starts now: the lease covers the run, not the queue wait.
        row.lease_expires_at = now + timedelta(seconds=settings.AI_TIMEOUT_SEC + 15)
        row.updated_at = now
        task = AiTask.model_validate({name: getattr(row, name) for name in AiTask.model_fields if name != "proposals"} | {"proposals": []})
        user = CurrentUser(id=row.owner_user_id, company_id=row.company_id,
                           role=conversation.owner_role if conversation else "ADMIN",
                           admin_scope=conversation.admin_scope if conversation else None)
        attempt_id = row.attempt_id
        session.commit()
        return task, attempt_id, user
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def run_once() -> int:
    """Execute at most one queued task. Returns 1 when a task was claimed."""
    claimed = claim_next()
    if claimed is None:
        return 0
    task, attempt_id, user = claimed
    uow_factory = SqlAlchemyUnitOfWork
    store = TaskStore(user, uow_factory, settings.AI_TIMEOUT_SEC)
    try:
        execute_task(task, attempt_id, user, uow_factory, store)
    except Forbidden:
        # Recorded as AI_ACCESS_CHANGED by execute_task; nothing reaches the actor.
        print(f"ai task {task.id}: access changed, answer discarded")
    except Exception as exc:  # the task is marked FAILED; the worker keeps serving others
        print(f"ai task {task.id} failed: {type(exc).__name__}")
    return 1


def main() -> None:
    print("DIMAX AI worker started" + ("" if settings.AI_EXECUTION_MODE == "background" else " (AI_EXECUTION_MODE is inline: nothing is queued)"))
    while True:
        try:
            processed = run_once()
        except Exception as exc:  # database hiccup: wait and try again
            print(f"ai worker loop error: {type(exc).__name__}")
            processed = 0
        time.sleep(0.2 if processed else settings.AI_WORKER_POLL_SEC)


if __name__ == "__main__":
    main()
