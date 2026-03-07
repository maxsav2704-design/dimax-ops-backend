from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from app.core.config import settings
from app.modules.audit.infrastructure.models import AuditLogORM
from app.modules.door_types.infrastructure.models import DoorTypeORM
from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.issues.domain.enums import IssueStatus
from app.modules.issues.infrastructure.models import IssueORM
from app.modules.issues.infrastructure.repositories import DELIVERY_OUTBOX_RISK_TITLE
from app.modules.journal.domain.enums import JournalDeliveryStatus, JournalStatus
from app.modules.journal.infrastructure.models import JournalORM
from app.modules.outbox.domain.enums import DeliveryStatus, OutboxChannel, OutboxStatus
from app.modules.outbox.infrastructure.models import OutboxMessageORM
from app.modules.projects.domain.enums import ProjectStatus
from app.modules.projects.infrastructure.models import ProjectORM
from app.webhooks.models import WebhookEventORM


def _seed_outbox_context(
    db_session,
    *,
    company_id,
    channel: OutboxChannel,
    provider_message_id: str | None,
) -> OutboxMessageORM:
    project = ProjectORM(
        company_id=company_id,
        name=f"Webhook Project {uuid.uuid4().hex[:8]}",
        address="Webhook Street",
        status=ProjectStatus.OK,
    )
    db_session.add(project)
    db_session.flush()

    door_type = DoorTypeORM(
        company_id=company_id,
        code=f"webhook-{uuid.uuid4().hex[:6]}",
        name="Webhook Door Type",
        is_active=True,
    )
    db_session.add(door_type)
    db_session.flush()

    db_session.add(
        DoorORM(
            company_id=company_id,
            project_id=project.id,
            door_type_id=door_type.id,
            unit_label=f"WB-{uuid.uuid4().hex[:6]}",
            our_price=Decimal("100.00"),
            status=DoorStatus.NOT_INSTALLED,
            installer_id=None,
            reason_id=None,
            comment=None,
            installed_at=None,
            is_locked=False,
        )
    )

    journal = JournalORM(
        company_id=company_id,
        project_id=project.id,
        status=JournalStatus.DRAFT,
        title="Webhook Journal",
        notes=None,
        public_token=None,
        public_token_expires_at=None,
        lock_header=False,
        lock_table=False,
        lock_footer=False,
        signed_at=None,
        signer_name=None,
        snapshot_version=1,
        email_delivery_status=JournalDeliveryStatus.PENDING,
        whatsapp_delivery_status=JournalDeliveryStatus.PENDING,
    )
    db_session.add(journal)
    db_session.flush()

    msg = OutboxMessageORM(
        company_id=company_id,
        channel=channel,
        status=OutboxStatus.SENT,
        correlation_id=journal.id,
        payload={"source": "test"},
        attempts=1,
        max_attempts=5,
        last_error=None,
        scheduled_at=datetime.now(timezone.utc),
        sent_at=datetime.now(timezone.utc),
        provider_message_id=provider_message_id,
        provider_status="sent",
        provider_error=None,
        delivery_status=DeliveryStatus.PENDING,
        delivered_at=None,
    )
    db_session.add(msg)
    db_session.commit()
    db_session.refresh(msg)
    return msg


def test_twilio_status_webhook_updates_outbox_and_creates_then_closes_delivery_risk_issue(
    client_raw,
    db_session,
    company_id,
):
    msg = _seed_outbox_context(
        db_session,
        company_id=company_id,
        channel=OutboxChannel.WHATSAPP,
        provider_message_id="SMTWILIO1",
    )

    fail_resp = client_raw.post(
        f"/api/v1/webhooks/twilio/status?outbox_id={msg.id}",
        data={
            "MessageSid": "SMTWILIO1",
            "MessageStatus": "failed",
            "ErrorCode": "30003",
            "ErrorMessage": "unreachable destination",
        },
    )
    assert fail_resp.status_code == 200, fail_resp.text
    assert fail_resp.text == "ok"

    db_session.refresh(msg)
    assert msg.delivery_status == DeliveryStatus.FAILED
    assert msg.status == OutboxStatus.FAILED
    assert msg.provider_status == "failed"
    assert "30003" in (msg.provider_error or "")

    journal = db_session.query(JournalORM).filter(JournalORM.id == msg.correlation_id).one()
    assert journal.whatsapp_delivery_status == JournalDeliveryStatus.FAILED

    issue = (
        db_session.query(IssueORM)
        .filter(
            IssueORM.company_id == company_id,
            IssueORM.title == DELIVERY_OUTBOX_RISK_TITLE,
        )
        .first()
    )
    assert issue is not None
    assert issue.status == IssueStatus.OPEN

    webhook_count_before = (
        db_session.query(WebhookEventORM)
        .filter(
            WebhookEventORM.provider == "twilio",
            WebhookEventORM.company_id == company_id,
        )
        .count()
    )

    duplicate_resp = client_raw.post(
        f"/api/v1/webhooks/twilio/status?outbox_id={msg.id}",
        data={
            "MessageSid": "SMTWILIO1",
            "MessageStatus": "failed",
            "ErrorCode": "30003",
            "ErrorMessage": "unreachable destination",
        },
    )
    assert duplicate_resp.status_code == 200, duplicate_resp.text
    webhook_count_after = (
        db_session.query(WebhookEventORM)
        .filter(
            WebhookEventORM.provider == "twilio",
            WebhookEventORM.company_id == company_id,
        )
        .count()
    )
    assert webhook_count_after == webhook_count_before

    ok_resp = client_raw.post(
        f"/api/v1/webhooks/twilio/status?outbox_id={msg.id}",
        data={
            "MessageSid": "SMTWILIO1",
            "MessageStatus": "delivered",
        },
    )
    assert ok_resp.status_code == 200, ok_resp.text

    db_session.refresh(msg)
    db_session.refresh(journal)
    db_session.refresh(issue)
    assert msg.delivery_status == DeliveryStatus.DELIVERED
    assert msg.status == OutboxStatus.SENT
    assert journal.whatsapp_delivery_status == JournalDeliveryStatus.DELIVERED
    assert issue.status == IssueStatus.CLOSED

    actions = {
        row.action
        for row in db_session.query(AuditLogORM)
        .filter(
            AuditLogORM.company_id == company_id,
            AuditLogORM.entity_type.in_(["outbox_message", "issue"]),
        )
        .all()
    }
    assert "OUTBOX_DELIVERY_STATUS_WEBHOOK" in actions
    assert "OUTBOX_DELIVERY_RISK_OPEN" in actions
    assert "OUTBOX_DELIVERY_RISK_CLOSE" in actions


def test_outbox_generic_status_webhook_resolves_by_provider_message_and_supports_token(
    client_raw,
    db_session,
    company_id,
    monkeypatch,
):
    msg = _seed_outbox_context(
        db_session,
        company_id=company_id,
        channel=OutboxChannel.EMAIL,
        provider_message_id="SG-EVENT-1",
    )

    resp = client_raw.post(
        "/api/v1/webhooks/outbox/status",
        json={
            "provider": "sendgrid",
            "channel": "EMAIL",
            "provider_message_id": "SG-EVENT-1",
            "event_id": "evt-1",
            "status": "delivered",
            "payload": {"source": "sendgrid"},
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.text == "ok"

    db_session.refresh(msg)
    assert msg.delivery_status == DeliveryStatus.DELIVERED
    assert msg.status == OutboxStatus.SENT
    assert msg.provider_status == "delivered"

    journal = db_session.query(JournalORM).filter(JournalORM.id == msg.correlation_id).one()
    assert journal.email_delivery_status == JournalDeliveryStatus.DELIVERED

    events_count = (
        db_session.query(WebhookEventORM)
        .filter(
            WebhookEventORM.provider == "sendgrid",
            WebhookEventORM.external_id == "evt-1",
            WebhookEventORM.company_id == company_id,
        )
        .count()
    )
    assert events_count == 1

    duplicate = client_raw.post(
        "/api/v1/webhooks/outbox/status",
        json={
            "provider": "sendgrid",
            "channel": "EMAIL",
            "provider_message_id": "SG-EVENT-1",
            "event_id": "evt-1",
            "status": "delivered",
        },
    )
    assert duplicate.status_code == 200, duplicate.text
    duplicate_count = (
        db_session.query(WebhookEventORM)
        .filter(
            WebhookEventORM.provider == "sendgrid",
            WebhookEventORM.external_id == "evt-1",
            WebhookEventORM.company_id == company_id,
        )
        .count()
    )
    assert duplicate_count == 1

    monkeypatch.setattr(settings, "OUTBOX_WEBHOOK_TOKEN", "secret-webhook-token")
    forbidden = client_raw.post(
        "/api/v1/webhooks/outbox/status",
        json={
            "provider": "sendgrid",
            "channel": "EMAIL",
            "provider_message_id": "SG-EVENT-1",
            "event_id": "evt-2",
            "status": "delivered",
        },
    )
    assert forbidden.status_code == 403, forbidden.text

    allowed = client_raw.post(
        "/api/v1/webhooks/outbox/status",
        headers={"X-Webhook-Token": "secret-webhook-token"},
        json={
            "provider": "sendgrid",
            "channel": "EMAIL",
            "provider_message_id": "SG-EVENT-1",
            "event_id": "evt-2",
            "status": "delivered",
        },
    )
    assert allowed.status_code == 200, allowed.text
