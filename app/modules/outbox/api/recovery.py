from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.v1.deps import CurrentUser, get_uow, require_admin
from app.modules.outbox.api.recovery_schemas import (
    RecoveryDecisionBody, RecoveryDecisionDTO, RecoveryItemDTO, RecoveryReason, RecoveryStatusDTO,
)
from app.modules.outbox.application.recovery_service import OutboxRecoveryService as Service

router = APIRouter(prefix="/recovery", tags=["Admin / Outbox recovery"])


@router.get("", response_model=RecoveryStatusDTO)
def status(user: CurrentUser = Depends(require_admin), uow=Depends(get_uow)):
    with uow:
        return Service.status(uow, user)


@router.post("/begin", response_model=RecoveryStatusDTO)
def begin(body: RecoveryReason, user: CurrentUser = Depends(require_admin), uow=Depends(get_uow)):
    with uow:
        return Service.begin(uow, user, body)


@router.get("/items", response_model=list[RecoveryItemDTO])
def items(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200),
          user: CurrentUser = Depends(require_admin), uow=Depends(get_uow)):
    with uow:
        return Service.items(uow, user, offset=offset, limit=limit)


@router.get("/decisions", response_model=list[RecoveryDecisionDTO])
def decisions(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200),
              user: CurrentUser = Depends(require_admin), uow=Depends(get_uow)):
    with uow:
        return Service.decisions(uow, user, offset=offset, limit=limit)


@router.post("/items/{item_id}/decisions", response_model=RecoveryDecisionDTO)
def decide(item_id: UUID, body: RecoveryDecisionBody,
           user: CurrentUser = Depends(require_admin), uow=Depends(get_uow)):
    with uow:
        return Service.decide(uow, user, item_id, body)


@router.post("/release", response_model=RecoveryStatusDTO)
def release(body: RecoveryReason, user: CurrentUser = Depends(require_admin), uow=Depends(get_uow)):
    with uow:
        return Service.release(uow, user, body)
