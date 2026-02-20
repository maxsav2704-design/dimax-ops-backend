from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.v1.deps import CurrentUser, get_uow, require_admin
from app.modules.outbox.api.admin_schemas import OutboxItemDTO, OutboxListResponse
from app.modules.outbox.infrastructure.models import OutboxMessageORM
from app.shared.domain.errors import NotFound


router = APIRouter(prefix="/admin/outbox", tags=["Admin / Outbox"])


@router.get("", response_model=OutboxListResponse)
def list_outbox(
    journal_id: UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        q = uow.session.query(OutboxMessageORM).filter(
            OutboxMessageORM.company_id == user.company_id
        )
        if journal_id is not None:
            q = q.filter(OutboxMessageORM.correlation_id == journal_id)

        rows = (
            q.order_by(OutboxMessageORM.created_at.desc())
            .limit(limit)
            .all()
        )
        return OutboxListResponse(
            items=[
                OutboxItemDTO(
                    id=r.id,
                    channel=str(r.channel),
                    status=str(r.status),
                    provider_message_id=r.provider_message_id,
                    provider_status=r.provider_status,
                    provider_error=r.provider_error,
                    attempts=r.attempts,
                    created_at=r.created_at,
                    sent_at=r.sent_at,
                    delivery_status=str(r.delivery_status),
                    delivered_at=r.delivered_at,
                )
                for r in rows
            ]
        )


@router.get("/{outbox_id}", response_model=OutboxItemDTO)
def get_outbox(
    outbox_id: UUID,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        r = (
            uow.session.query(OutboxMessageORM)
            .filter(
                OutboxMessageORM.company_id == user.company_id,
                OutboxMessageORM.id == outbox_id,
            )
            .one_or_none()
        )
        if not r:
            raise NotFound(
                "Outbox message not found",
                details={"outbox_id": str(outbox_id)},
            )
        return OutboxItemDTO(
            id=r.id,
            channel=str(r.channel),
            status=str(r.status),
            provider_message_id=r.provider_message_id,
            provider_status=r.provider_status,
            provider_error=r.provider_error,
            attempts=r.attempts,
            created_at=r.created_at,
            sent_at=r.sent_at,
            delivery_status=str(r.delivery_status),
            delivered_at=r.delivered_at,
        )
