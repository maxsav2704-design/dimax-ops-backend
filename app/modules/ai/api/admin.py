from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response

from app.api.v1.deps import CurrentUser, get_current_user, get_uow
from app.api.v1.rate_limit import _allow
from app.core.config import settings
from app.modules.ai.api.routes import ai_status, build_provider, register_ai_routes, require_ready
from app.modules.ai.api.schemas import AiCheck, AiReply, AiRequest, AiRules, AiRulesUpdate
from app.modules.ai.application.rules_service import AiRulesService
from app.modules.ai.application.runner import AiRunner
from app.modules.ai.domain.tools import ensure_ai_admin
from app.shared.domain.errors import ForbiddenScope
from app.modules.ai.infrastructure.provider import AiProviderError
from app.modules.ai.infrastructure.read_tools import ReadTools
from app.modules.audit.application.service import AuditService


router = APIRouter(prefix="/admin/ai", tags=["Admin / DIMAX AI"])


def require_ai_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    # POST starts a read-only run or records a decision on a proposal; business
    # commands run only inside ProposalStore.confirm with the write-scope check.
    return ensure_ai_admin(user)


register_ai_routes(router, require_ai_admin)


def require_ai_owner(user: CurrentUser = Depends(require_ai_admin)) -> CurrentUser:
    if user.admin_scope != "OWNER":
        raise ForbiddenScope("Only the company owner may change DIMAX AI rules or check the connection")
    return user


@router.get("/rules", response_model=AiRules)
def get_rules(response: Response, user: CurrentUser = Depends(require_ai_admin), uow=Depends(get_uow)):
    # Reviewable by every admin profile; changed only by the owner.
    response.headers["Cache-Control"] = "no-store"
    with uow:
        return AiRulesService.view(uow, AiRulesService.current(uow, user.company_id))


@router.put("/rules", response_model=AiRules)
def put_rules(body: AiRulesUpdate, response: Response, user: CurrentUser = Depends(require_ai_owner), uow=Depends(get_uow)):
    response.headers["Cache-Control"] = "no-store"
    with uow:
        row = AiRulesService.set_rules(uow, company_id=user.company_id, actor_user_id=user.id, text=body.text)
        return AiRulesService.view(uow, row)


@router.post("/check", response_model=AiCheck)
def check_connection(response: Response, user: CurrentUser = Depends(require_ai_owner), uow=Depends(get_uow)):
    """One minimal provider round trip without tools or business data; the owner's release gate for a real key."""
    response.headers["Cache-Control"] = "no-store"
    _allow(f"ai-check:{user.company_id}", window=60, max_req=3)
    require_ready()
    provider = build_provider()
    started = time.monotonic()
    ok, code, preview = False, None, None
    try:
        data = provider.respond(instructions="Reply with the single word OK.", items=[{"role": "user", "content": "ping"}], tools=[], timeout=20)
        text = "\n".join(part.get("text", "") for item in data.get("output", []) if isinstance(item, dict) and item.get("type") == "message"
                         for part in item.get("content", []) if isinstance(part, dict) and part.get("type") == "output_text").strip()
        ok, preview = True, text[:40]
    except AiProviderError as exc:
        code = exc.code
    latency = round((time.monotonic() - started) * 1000)
    with uow:
        AuditService.add(uow, company_id=user.company_id, actor_user_id=user.id, entity_type="AiRun", entity_id=uuid.uuid4(),
                         action="AI_CONNECTION_CHECK", after={"ok": ok, "code": code, "latency_ms": latency,
                                                               "provider": getattr(provider, "name", "openai")})
    return AiCheck(ok=ok, provider=getattr(provider, "name", "openai"), model=settings.AI_MODEL.strip() or None,
                   latency_ms=latency, code=code, answer_preview=preview)


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
