from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.v1.deps import CurrentUser, get_uow, require_admin
from app.modules.audit.application.service import AuditService
from app.modules.outbox.application.admin_service import OutboxAdminService
from app.modules.outbox.api.admin_schemas import (
    OutboxItemDTO,
    OutboxListResponse,
    OutboxRetryBody,
    OutboxRetryResponse,
    OutboxSummaryResponse,
)


router = APIRouter(prefix="/admin/outbox", tags=["Admin / Outbox"])


@router.get("", response_model=OutboxListResponse)
def list_outbox(
    journal_id: UUID | None = Query(default=None),
    channel: str | None = Query(default=None),
    status: str | None = Query(default=None),
    delivery_status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return OutboxAdminService.list_outbox(
            uow,
            company_id=user.company_id,
            journal_id=journal_id,
            channel=channel,
            status=status,
            delivery_status=delivery_status,
            limit=limit,
        )


@router.get("/summary", response_model=OutboxSummaryResponse)
def outbox_summary(
    journal_id: UUID | None = Query(default=None),
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return OutboxAdminService.summary_outbox(
            uow,
            company_id=user.company_id,
            journal_id=journal_id,
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


@router.post("/{outbox_id}/retry", response_model=OutboxRetryResponse)
def retry_outbox(
    outbox_id: UUID,
    body: OutboxRetryBody,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        item, before, after = OutboxAdminService.retry_outbox(
            uow,
            company_id=user.company_id,
            outbox_id=outbox_id,
        )
        AuditService.add(
            uow,
            company_id=user.company_id,
            actor_user_id=user.id,
            entity_type="outbox_message",
            entity_id=outbox_id,
            action="OUTBOX_RETRY",
            reason=body.reason,
            before=before,
            after=after,
        )
        return OutboxRetryResponse(item=item)
