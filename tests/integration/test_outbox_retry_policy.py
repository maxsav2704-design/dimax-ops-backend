"""Outbox retry policy (sync audit block 4): backoff between attempts and one
fallback email per WhatsApp message, not one per failed attempt."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.modules.outbox.domain.enums import OutboxChannel, OutboxStatus
from app.modules.outbox.infrastructure.models import OutboxMessageORM
from app.modules.outbox.infrastructure.repositories import OutboxRepository
from app.workers.outbox_worker import _enqueue_whatsapp_fallback_email


def _whatsapp_message(company_id, *, correlation_id=None, max_attempts=5) -> OutboxMessageORM:
    return OutboxMessageORM(
        company_id=company_id,
        channel=OutboxChannel.WHATSAPP,
        status=OutboxStatus.PENDING,
        correlation_id=correlation_id,
        payload={
            "to_phone": "+15550001111",
            "body_text": "Journal",
            "object_key": "journals/test.pdf",
            "fallback_email": "client@example.com",
        },
        attempts=0,
        max_attempts=max_attempts,
        scheduled_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )


def test_mark_failed_backs_off_before_the_next_attempt(db_session, company_id):
    repo = OutboxRepository(db_session)
    msg = _whatsapp_message(company_id)
    db_session.add(msg)
    db_session.flush()
    before = datetime.now(timezone.utc)

    repo.mark_failed(msg, error="provider down")
    assert msg.status == OutboxStatus.PENDING
    assert msg.attempts == 1
    assert msg.scheduled_at >= before + timedelta(minutes=1) - timedelta(seconds=5)
    # Not eligible for the next batch right away.
    assert msg not in repo.lock_next_batch(company_id=company_id, limit=20)

    repo.mark_failed(msg, error="provider down")
    assert msg.scheduled_at >= before + timedelta(minutes=5) - timedelta(seconds=5)

    for _ in range(3):
        repo.mark_failed(msg, error="provider down")
    assert msg.attempts == 5
    assert msg.status == OutboxStatus.FAILED


def test_retry_delay_escalates_and_caps():
    assert [OutboxRepository.retry_delay_minutes(n) for n in (1, 2, 3, 4, 5, 9)] == [1, 5, 15, 60, 60, 60]


def test_whatsapp_fallback_email_is_enqueued_once(db_session, company_id, monkeypatch):
    monkeypatch.setattr(settings, "WHATSAPP_FALLBACK_TO_EMAIL", True)
    repo = OutboxRepository(db_session)
    msg = _whatsapp_message(company_id, correlation_id=uuid.uuid4())
    db_session.add(msg)
    db_session.flush()

    assert _enqueue_whatsapp_fallback_email(repo, msg, payload=msg.payload, error="first failure") is True
    db_session.flush()
    assert _enqueue_whatsapp_fallback_email(repo, msg, payload=msg.payload, error="second failure") is False

    fallbacks = (
        db_session.query(OutboxMessageORM)
        .filter(
            OutboxMessageORM.company_id == company_id,
            OutboxMessageORM.channel == OutboxChannel.EMAIL,
            OutboxMessageORM.correlation_id == msg.correlation_id,
        )
        .all()
    )
    assert len(fallbacks) == 1
    assert fallbacks[0].payload["fallback_reason"] == "first failure"
