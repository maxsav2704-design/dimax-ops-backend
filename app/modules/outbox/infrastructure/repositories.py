from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.modules.outbox.domain.enums import OutboxStatus
from app.modules.outbox.infrastructure.models import OutboxMessageORM


class OutboxRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def enqueue(self, msg: OutboxMessageORM) -> None:
        self.session.add(msg)

    def lock_next_batch(
        self,
        *,
        company_id: uuid.UUID | None = None,
        limit: int = 20,
    ) -> list[OutboxMessageORM]:
        q = self.session.query(OutboxMessageORM).filter(
            OutboxMessageORM.status == OutboxStatus.PENDING,
            OutboxMessageORM.scheduled_at <= datetime.now(timezone.utc),
        )
        if company_id is not None:
            q = q.filter(OutboxMessageORM.company_id == company_id)

        return (
            q.order_by(OutboxMessageORM.created_at.asc())
            .with_for_update(skip_locked=True)
            .limit(limit)
            .all()
        )

    def mark_sent(self, msg: OutboxMessageORM) -> None:
        msg.status = OutboxStatus.SENT
        msg.sent_at = datetime.now(timezone.utc)
        self.session.add(msg)

    def mark_failed(self, msg: OutboxMessageORM, *, error: str) -> None:
        msg.attempts += 1
        msg.last_error = error[:5000]
        if msg.attempts >= msg.max_attempts:
            msg.status = OutboxStatus.FAILED
        self.session.add(msg)

    def set_provider_status(
        self,
        msg: OutboxMessageORM,
        *,
        provider_message_id: str | None = None,
        provider_status: str | None = None,
        provider_error: str | None = None,
    ) -> None:
        if provider_message_id is not None:
            msg.provider_message_id = provider_message_id
        if provider_status is not None:
            msg.provider_status = provider_status
        if provider_error is not None:
            msg.provider_error = provider_error[:5000]
        self.session.add(msg)

    def get_by_provider_message_id(
        self, provider_message_id: str
    ) -> OutboxMessageORM | None:
        return (
            self.session.query(OutboxMessageORM)
            .filter(
                OutboxMessageORM.provider_message_id == provider_message_id
            )
            .one_or_none()
        )
