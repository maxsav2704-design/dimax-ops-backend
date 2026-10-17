from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.modules.journal.infrastructure.models import JournalORM
from app.modules.outbox.domain.enums import DeliveryStatus, OutboxChannel, OutboxStatus
from app.modules.outbox.infrastructure.models import OutboxMessageORM


class OutboxRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def enqueue(self, msg: OutboxMessageORM) -> None:
        self.session.add(msg)

    def get(
        self, *, company_id: uuid.UUID, outbox_id: uuid.UUID
    ) -> OutboxMessageORM | None:
        return (
            self.session.query(OutboxMessageORM)
            .filter(
                OutboxMessageORM.company_id == company_id,
                OutboxMessageORM.id == outbox_id,
            )
            .one_or_none()
        )

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

    # Minutes before the next attempt after the 1st, 2nd, ... failure; the last
    # value repeats. Before this the worker retried every ~3 s and used up all
    # attempts within seconds of a provider outage.
    RETRY_BACKOFF_MINUTES = (1, 5, 15, 60)

    @classmethod
    def retry_delay_minutes(cls, attempts: int) -> int:
        index = max(0, min(attempts, len(cls.RETRY_BACKOFF_MINUTES)) - 1)
        return cls.RETRY_BACKOFF_MINUTES[index]

    def mark_failed(self, msg: OutboxMessageORM, *, error: str) -> None:
        msg.attempts += 1
        msg.last_error = error[:5000]
        if msg.attempts >= msg.max_attempts:
            msg.status = OutboxStatus.FAILED
        else:
            msg.scheduled_at = datetime.now(timezone.utc) + timedelta(
                minutes=self.retry_delay_minutes(msg.attempts)
            )
        self.session.add(msg)

    def has_fallback_email(self, msg: OutboxMessageORM) -> bool:
        """A WhatsApp message gets at most one fallback email, whatever the attempt."""
        if msg.correlation_id is None:
            return False
        return (
            self.session.query(OutboxMessageORM.id)
            .filter(
                OutboxMessageORM.company_id == msg.company_id,
                OutboxMessageORM.channel == OutboxChannel.EMAIL,
                OutboxMessageORM.correlation_id == msg.correlation_id,
                OutboxMessageORM.payload["fallback_reason"].isnot(None),
            )
            .first()
            is not None
        )

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

    def count_failed_delivery_for_project(
        self,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID,
        window_hours: int,
    ) -> int:
        since = datetime.now(timezone.utc)
        if int(window_hours) > 0:
            since = since - timedelta(hours=int(window_hours))

        q = (
            self.session.query(OutboxMessageORM.id)
            .join(
                JournalORM,
                and_(
                    JournalORM.company_id == OutboxMessageORM.company_id,
                    JournalORM.id == OutboxMessageORM.correlation_id,
                ),
            )
            .filter(
                OutboxMessageORM.company_id == company_id,
                JournalORM.project_id == project_id,
                OutboxMessageORM.created_at >= since,
                or_(
                    OutboxMessageORM.delivery_status == DeliveryStatus.FAILED,
                    OutboxMessageORM.status == OutboxStatus.FAILED,
                ),
            )
        )
        return int(q.count())
