from __future__ import annotations

import uuid

from app.modules.outbox.api.admin_schemas import OutboxItemDTO, OutboxListResponse
from app.modules.outbox.infrastructure.models import OutboxMessageORM
from app.shared.domain.errors import NotFound


def _to_dto(row: OutboxMessageORM) -> OutboxItemDTO:
    return OutboxItemDTO(
        id=row.id,
        channel=str(row.channel),
        status=str(row.status),
        provider_message_id=row.provider_message_id,
        provider_status=row.provider_status,
        provider_error=row.provider_error,
        attempts=row.attempts,
        created_at=row.created_at,
        sent_at=row.sent_at,
        delivery_status=str(row.delivery_status),
        delivered_at=row.delivered_at,
    )


class OutboxAdminService:
    @staticmethod
    def list_outbox(
        uow,
        *,
        company_id: uuid.UUID,
        journal_id: uuid.UUID | None,
        limit: int,
    ) -> OutboxListResponse:
        q = uow.session.query(OutboxMessageORM).filter(
            OutboxMessageORM.company_id == company_id
        )
        if journal_id is not None:
            q = q.filter(OutboxMessageORM.correlation_id == journal_id)

        rows = q.order_by(OutboxMessageORM.created_at.desc()).limit(limit).all()
        return OutboxListResponse(items=[_to_dto(r) for r in rows])

    @staticmethod
    def get_outbox(
        uow,
        *,
        company_id: uuid.UUID,
        outbox_id: uuid.UUID,
    ) -> OutboxItemDTO:
        row = (
            uow.session.query(OutboxMessageORM)
            .filter(
                OutboxMessageORM.company_id == company_id,
                OutboxMessageORM.id == outbox_id,
            )
            .one_or_none()
        )
        if not row:
            raise NotFound(
                "Outbox message not found",
                details={"outbox_id": str(outbox_id)},
            )
        return _to_dto(row)
