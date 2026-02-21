from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.v1.deps import CurrentUser, get_uow, require_admin
from app.modules.outbox.application.admin_service import OutboxAdminService
from app.modules.outbox.api.admin_schemas import OutboxItemDTO, OutboxListResponse


router = APIRouter(prefix="/admin/outbox", tags=["Admin / Outbox"])


@router.get("", response_model=OutboxListResponse)
def list_outbox(
    journal_id: UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return OutboxAdminService.list_outbox(
            uow,
            company_id=user.company_id,
            journal_id=journal_id,
            limit=limit,
        )


@router.get("/{outbox_id}", response_model=OutboxItemDTO)
def get_outbox(
    outbox_id: UUID,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return OutboxAdminService.get_outbox(
            uow,
            company_id=user.company_id,
            outbox_id=outbox_id,
        )
