from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response

from app.api.v1.deps import CurrentUser, get_current_user, get_uow
from app.api.v1.rate_limit import _allow
from app.core.config import settings
from app.modules.ai.api.routes import ai_status, build_provider, register_ai_routes
from app.modules.ai.api.schemas import AiReply, AiRequest
from app.modules.ai.application.runner import AiRunner
from app.modules.ai.domain.tools import ensure_ai_admin
from app.modules.ai.infrastructure.provider import AiProviderError
from app.modules.ai.infrastructure.read_tools import ReadTools
from app.modules.audit.application.service import AuditService


router = APIRouter(prefix="/admin/ai", tags=["Admin / DIMAX AI"])


def require_ai_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    # POST starts a read-only run or records a decision on a proposal; business
    # commands run only inside ProposalStore.confirm with the write-scope check.
    return ensure_ai_admin(user)


register_ai_routes(router, require_ai_admin)


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
