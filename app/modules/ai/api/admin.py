from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from uuid import UUID

from app.api.v1.deps import CurrentUser, get_current_user, get_uow
from app.api.v1.rate_limit import _allow
from app.core.config import settings
from app.modules.ai.api.schemas import (AiConfirmRequest, AiConversationPage, AiProposal, AiReply, AiRequest, AiRetryRequest,
                                        AiStatus, AiTask, AiTaskPage, AiTaskRequest)
from app.modules.ai.application.runner import AiRunner
from app.modules.ai.domain.tools import actions_available, allowed_tool_names, ensure_ai_admin
from app.modules.ai.infrastructure.mock_provider import MockProvider
from app.modules.ai.infrastructure.proposal_store import ProposalStore
from app.modules.ai.infrastructure.provider import AiProviderError, ResponsesProvider
from app.modules.ai.infrastructure.read_tools import ReadTools
from app.modules.ai.infrastructure.task_store import TaskStore
from app.shared.domain.errors import Forbidden
from app.modules.audit.application.service import AuditService


router = APIRouter(prefix="/admin/ai", tags=["Admin / DIMAX AI"])


def require_ai_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    # POST starts a read-only run or records a decision on a proposal; business
    # commands run only inside ProposalStore.confirm with the write-scope check.
    return ensure_ai_admin(user)


def provider_name() -> str:
    return "mock" if settings.AI_PROVIDER.strip().lower() == "mock" else "openai"


def ai_status(user: CurrentUser) -> AiStatus:
    reason = "ready"
    if provider_name() == "openai" and not settings.OPENAI_API_KEY.get_secret_value().strip():
        reason = "missing_api_key"
    elif provider_name() == "openai" and not settings.AI_MODEL.strip():
        reason = "missing_model"
    elif not settings.AI_ENABLED:
        reason = "disabled"
    return AiStatus(ready=reason == "ready", reason=reason, tools=allowed_tool_names(user),
                    provider=provider_name(), actions_enabled=actions_available(user))


@router.get("/status", response_model=AiStatus)
def status(response: Response, user: CurrentUser = Depends(require_ai_admin)):
    response.headers["Cache-Control"] = "no-store"
    return ai_status(user)


def store_for(user, uow):
    return TaskStore(user, lambda: uow, settings.AI_TIMEOUT_SEC)


def proposals_for(user, uow):
    return ProposalStore(user, lambda: uow, settings)


def require_ready():
    if not ai_status_reason_ready():
        raise HTTPException(503, detail={"code": "AI_NOT_CONFIGURED", "message": "DIMAX AI is not configured"},
                            headers={"Cache-Control": "no-store"})


def ai_status_reason_ready():
    if provider_name() == "mock":
        return bool(settings.AI_ENABLED)
    return bool(settings.OPENAI_API_KEY.get_secret_value().strip() and settings.AI_MODEL.strip() and settings.AI_ENABLED)


def build_provider():
    if provider_name() == "mock":
        return MockProvider()
    return ResponsesProvider(api_key=settings.OPENAI_API_KEY.get_secret_value(),
                             model=settings.AI_MODEL.strip(), max_output_tokens=settings.AI_MAX_OUTPUT_TOKENS)


def execute_task(task, attempt_id, user, uow, store):
    if attempt_id is None:
        return task
    tools = ReadTools(user, lambda: uow, proposals=proposals_for(user, uow), task_id=task.id, conversation_id=task.conversation_id)
    runner = AiRunner(provider=build_provider(), tools=tools, settings=settings)
    started = time.monotonic()
    def stats():
        return {"tools": runner.tools_used, "provider_requests": runner.provider_requests,
                "duration_ms": round((time.monotonic() - started) * 1000)}
    try:
        result = runner.run(AiRequest(message=task.message, locale=task.locale, project_id=task.project_id, context=task.context), task.id,
            history=store.history(task.id, attempt_id), check_running=lambda: store.check_running(task.id, attempt_id))
        return store.finish(task.id, attempt_id, result, **stats())
    except Forbidden:
        store.fail(task.id, attempt_id, "AI_ACCESS_CHANGED", **stats())
        raise
    except AiProviderError as exc:
        store.fail(task.id, attempt_id, exc.code, **stats())
        return store.get(task.id)
    except Exception:
        store.fail(task.id, attempt_id, "AI_TASK_FAILED", **stats())
        raise


@router.get("/conversations", response_model=AiConversationPage)
def conversations(response: Response, limit: int = Query(20, ge=1, le=50), offset: int = Query(0, ge=0, le=10000),
                  user: CurrentUser = Depends(require_ai_admin), uow=Depends(get_uow)):
    response.headers["Cache-Control"] = "no-store"
    return store_for(user, uow).conversations(limit, offset)


@router.get("/conversations/{conversation_id}/tasks", response_model=AiTaskPage)
def conversation_tasks(conversation_id: UUID, response: Response, limit: int = Query(20, ge=1, le=50),
                       offset: int = Query(0, ge=0, le=10000), user: CurrentUser = Depends(require_ai_admin), uow=Depends(get_uow)):
    response.headers["Cache-Control"] = "no-store"
    return store_for(user, uow).tasks(conversation_id, limit, offset)


@router.get("/tasks/{task_id}", response_model=AiTask)
def task_status(task_id: UUID, response: Response, user: CurrentUser = Depends(require_ai_admin), uow=Depends(get_uow)):
    response.headers["Cache-Control"] = "no-store"
    return store_for(user, uow).get(task_id)


@router.post("/tasks", response_model=AiTask)
def create_task(body: AiTaskRequest, response: Response, user: CurrentUser = Depends(require_ai_admin), uow=Depends(get_uow)):
    response.headers["Cache-Control"] = "no-store"
    store = store_for(user, uow)
    existing = store.lookup(body)
    if existing:
        return existing
    require_ready()
    _allow(f"ai:{user.company_id}:{user.id}", window=60, max_req=6)
    task, attempt_id = store.start(body)
    return execute_task(task, attempt_id, user, uow, store)


@router.post("/tasks/{task_id}/retry", response_model=AiTask)
def retry_task(task_id: UUID, body: AiRetryRequest, response: Response, user: CurrentUser = Depends(require_ai_admin),
               uow=Depends(get_uow)):
    response.headers["Cache-Control"] = "no-store"
    store = store_for(user, uow)
    existing = store.lookup_retry(task_id, body.request_id)
    if existing:
        return existing
    require_ready()
    _allow(f"ai:{user.company_id}:{user.id}", window=60, max_req=6)
    task, attempt_id = store.retry(task_id, body.request_id)
    return execute_task(task, attempt_id, user, uow, store)


@router.post("/tasks/{task_id}/cancel", response_model=AiTask)
def cancel_task(task_id: UUID, response: Response, user: CurrentUser = Depends(require_ai_admin), uow=Depends(get_uow)):
    response.headers["Cache-Control"] = "no-store"
    return store_for(user, uow).cancel(task_id)


@router.get("/proposals/{proposal_id}", response_model=AiProposal)
def proposal_status(proposal_id: UUID, response: Response, user: CurrentUser = Depends(require_ai_admin), uow=Depends(get_uow)):
    response.headers["Cache-Control"] = "no-store"
    return proposals_for(user, uow).get(proposal_id)


@router.post("/proposals/{proposal_id}/confirm", response_model=AiProposal)
def confirm_proposal(proposal_id: UUID, body: AiConfirmRequest, response: Response,
                     user: CurrentUser = Depends(require_ai_admin), uow=Depends(get_uow)):
    # Confirmation does not need the provider: it executes the existing business command once.
    response.headers["Cache-Control"] = "no-store"
    _allow(f"ai-confirm:{user.company_id}:{user.id}", window=60, max_req=30)
    return proposals_for(user, uow).confirm(proposal_id, body.request_id)


@router.post("/proposals/{proposal_id}/reject", response_model=AiProposal)
def reject_proposal(proposal_id: UUID, response: Response, user: CurrentUser = Depends(require_ai_admin), uow=Depends(get_uow)):
    response.headers["Cache-Control"] = "no-store"
    return proposals_for(user, uow).reject(proposal_id)


@router.post("/query", response_model=AiReply, deprecated=True)
def query(body: AiRequest, response: Response, user: CurrentUser = Depends(require_ai_admin),
          uow=Depends(get_uow)):
    response.headers["Cache-Control"] = "no-store"
    if not ai_status(user).ready:
        raise HTTPException(503, detail={"code": "AI_NOT_CONFIGURED", "message": "DIMAX AI is not configured"},
                            headers={"Cache-Control": "no-store"})
    _allow(f"ai:{user.company_id}:{user.id}", window=60, max_req=6)
    run_id = uuid.uuid4()
    started = time.monotonic()
    # Legacy transient endpoint: read tools only, no proposals.
    runner = AiRunner(provider=build_provider(), tools=ReadTools(user, lambda: uow), settings=settings)
    outcome = "FAILED"
    try:
        result = runner.run(body, run_id)
        outcome = "COMPLETED"
        return result
    except AiProviderError as exc:
        raise HTTPException(503, detail={"code": exc.code,
            "message": "DIMAX AI could not complete the request. No business data was changed."},
            headers={"Cache-Control": "no-store"}) from None
    finally:
        # Metadata only: never persist prompt text, tool payloads, provider errors
        # or credentials to the generic activity log.
        with uow:
            AuditService.add(uow, company_id=user.company_id, actor_user_id=user.id,
                entity_type="AiRun", entity_id=run_id, action="AI_READ_QUERY",
                after={"status": outcome, "tools": runner.tools_used,
                       "provider_requests": runner.provider_requests,
                       "duration_ms": round((time.monotonic() - started) * 1000)})
