from __future__ import annotations

import uuid

from app.modules.audit.infrastructure.models import AuditLogORM
from app.modules.outbox.domain.enums import DeliveryStatus, OutboxChannel, OutboxStatus
from app.modules.outbox.infrastructure.models import OutboxMessageORM
from app.modules.projects.domain.enums import ProjectStatus
from app.modules.projects.infrastructure.models import ProjectORM


def _create_project(db_session, *, company_id: uuid.UUID, name: str) -> ProjectORM:
    row = ProjectORM(
        company_id=company_id,
        name=name,
        address=f"{name} address",
        status=ProjectStatus.OK,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def _create_journal(client_admin_real_uow, *, project_id: uuid.UUID) -> str:
    resp = client_admin_real_uow.post(
        "/api/v1/admin/journals",
        json={"project_id": str(project_id), "title": "Outbox Journal"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def test_outbox_admin_list_and_get(client_admin_real_uow, db_session, company_id):
    project = _create_project(
        db_session,
        company_id=company_id,
        name=f"Outbox Project {uuid.uuid4().hex[:8]}",
    )
    journal_id = _create_journal(client_admin_real_uow, project_id=project.id)

    ready_resp = client_admin_real_uow.post(
        f"/api/v1/admin/journals/{journal_id}/mark-ready"
    )
    assert ready_resp.status_code == 200, ready_resp.text

    send_resp = client_admin_real_uow.post(
        f"/api/v1/admin/journals/{journal_id}/send",
        json={
            "email_to": "client@example.com",
            "whatsapp_to": "+15550003333",
            "send_email": True,
            "send_whatsapp": True,
        },
    )
    assert send_resp.status_code == 200, send_resp.text

    list_resp = client_admin_real_uow.get(
        f"/api/v1/admin/outbox?journal_id={journal_id}&limit=10"
    )
    assert list_resp.status_code == 200, list_resp.text
    payload = list_resp.json()
    assert len(payload["items"]) >= 2

    first = payload["items"][0]
    assert "correlation_id" in first
    assert "scheduled_at" in first
    assert "max_attempts" in first
    assert first["status"].endswith(("PENDING", "SENT", "FAILED"))
    assert first["delivery_status"].endswith(("PENDING", "DELIVERED", "FAILED"))

    get_resp = client_admin_real_uow.get(f"/api/v1/admin/outbox/{first['id']}")
    assert get_resp.status_code == 200, get_resp.text
    assert get_resp.json()["id"] == first["id"]


def test_outbox_admin_filters_and_summary(
    client_admin_real_uow,
    db_session,
    company_id,
):
    project = _create_project(
        db_session,
        company_id=company_id,
        name=f"Outbox Filter Project {uuid.uuid4().hex[:8]}",
    )
    journal_id = _create_journal(client_admin_real_uow, project_id=project.id)
    ready_resp = client_admin_real_uow.post(
        f"/api/v1/admin/journals/{journal_id}/mark-ready"
    )
    assert ready_resp.status_code == 200, ready_resp.text

    send_resp = client_admin_real_uow.post(
        f"/api/v1/admin/journals/{journal_id}/send",
        json={
            "email_to": "client@example.com",
            "whatsapp_to": "+15550007777",
            "send_email": True,
            "send_whatsapp": True,
        },
    )
    assert send_resp.status_code == 200, send_resp.text

    filtered = client_admin_real_uow.get(
        "/api/v1/admin/outbox",
        params={"journal_id": journal_id, "channel": "EMAIL", "limit": 20},
    )
    assert filtered.status_code == 200, filtered.text
    items = filtered.json()["items"]
    assert len(items) >= 1
    assert all(item["channel"] == "EMAIL" for item in items)

    invalid_filter = client_admin_real_uow.get(
        "/api/v1/admin/outbox",
        params={"channel": "UNKNOWN"},
    )
    assert invalid_filter.status_code == 422, invalid_filter.text
    assert invalid_filter.json()["error"]["code"] == "VALIDATION_ERROR"

    summary_resp = client_admin_real_uow.get(
        "/api/v1/admin/outbox/summary",
        params={"journal_id": journal_id},
    )
    assert summary_resp.status_code == 200, summary_resp.text
    summary = summary_resp.json()
    for key in (
        "total",
        "by_channel",
        "by_status",
        "by_delivery_status",
        "pending_overdue_15m",
        "failed_total",
    ):
        assert key in summary
    assert summary["total"] >= 2


def test_outbox_admin_webhook_signals_summary_and_list(
    client_admin_real_uow,
    client_raw,
    db_session,
    company_id,
):
    from tests.integration.test_outbox_webhooks_api import _seed_outbox_context

    msg = _seed_outbox_context(
        db_session,
        company_id=company_id,
        channel=OutboxChannel.EMAIL,
        provider_message_id="SG-WEBHOOK-ADMIN-1",
    )

    delivered = client_raw.post(
        "/api/v1/webhooks/outbox/status",
        json={
            "provider": "sendgrid",
            "channel": "EMAIL",
            "provider_message_id": "SG-WEBHOOK-ADMIN-1",
            "event_id": "evt-admin-1",
            "status": "delivered",
        },
    )
    assert delivered.status_code == 200, delivered.text

    duplicate = client_raw.post(
        "/api/v1/webhooks/outbox/status",
        json={
            "provider": "sendgrid",
            "channel": "EMAIL",
            "provider_message_id": "SG-WEBHOOK-ADMIN-1",
            "event_id": "evt-admin-1",
            "status": "delivered",
        },
    )
    assert duplicate.status_code == 200, duplicate.text

    mismatch = client_raw.post(
        "/api/v1/webhooks/outbox/status",
        json={
            "provider": "sendgrid",
            "channel": "WHATSAPP",
            "provider_message_id": "SG-WEBHOOK-ADMIN-1",
            "event_id": "evt-admin-2",
            "status": "failed",
        },
    )
    assert mismatch.status_code == 200, mismatch.text

    summary_resp = client_admin_real_uow.get(
        "/api/v1/admin/outbox/webhook-signals/summary",
        params={"hours": 24},
    )
    assert summary_resp.status_code == 200, summary_resp.text
    summary = summary_resp.json()
    assert summary["total_received"] >= 3
    assert summary["updated_total"] >= 1
    assert summary["duplicate_total"] >= 1
    assert summary["unmatched_total"] >= 1
    assert summary["provider_failed_total"] >= 1

    list_resp = client_admin_real_uow.get(
        "/api/v1/admin/outbox/webhook-signals",
        params={"limit": 10},
    )
    assert list_resp.status_code == 200, list_resp.text
    items = list_resp.json()["items"]
    assert len(items) >= 3
    results = {item["result"] for item in items}
    assert "updated" in results
    assert "duplicate" in results
    assert "channel_mismatch" in results


def test_outbox_admin_retry_failed_message_and_writes_audit(
    client_admin_real_uow,
    db_session,
    company_id,
    admin_user,
):
    project = _create_project(
        db_session,
        company_id=company_id,
        name=f"Outbox Retry Project {uuid.uuid4().hex[:8]}",
    )
    journal_id = _create_journal(client_admin_real_uow, project_id=project.id)
    ready_resp = client_admin_real_uow.post(
        f"/api/v1/admin/journals/{journal_id}/mark-ready"
    )
    assert ready_resp.status_code == 200, ready_resp.text
    send_resp = client_admin_real_uow.post(
        f"/api/v1/admin/journals/{journal_id}/send",
        json={
            "email_to": "client@example.com",
            "send_email": True,
            "send_whatsapp": False,
        },
    )
    assert send_resp.status_code == 200, send_resp.text

    journal_uuid = uuid.UUID(journal_id)
    msg = (
        db_session.query(OutboxMessageORM)
        .filter(
            OutboxMessageORM.company_id == company_id,
            OutboxMessageORM.correlation_id == journal_uuid,
            OutboxMessageORM.channel == OutboxChannel.EMAIL,
        )
        .order_by(OutboxMessageORM.created_at.desc())
        .first()
    )
    assert msg is not None
    original_max = msg.max_attempts
    msg.status = OutboxStatus.FAILED
    msg.delivery_status = DeliveryStatus.FAILED
    msg.attempts = msg.max_attempts
    msg.last_error = "smtp unavailable"
    db_session.add(msg)
    db_session.commit()

    retry_resp = client_admin_real_uow.post(
        f"/api/v1/admin/outbox/{msg.id}/retry",
        json={"reason": "manual retry from reports"},
    )
    assert retry_resp.status_code == 200, retry_resp.text
    retry_item = retry_resp.json()["item"]
    assert retry_item["id"] == str(msg.id)
    assert retry_item["status"] == "PENDING"
    assert retry_item["delivery_status"] == "PENDING"

    db_session.refresh(msg)
    assert msg.status == OutboxStatus.PENDING
    assert msg.delivery_status == DeliveryStatus.PENDING
    assert msg.last_error is None
    assert msg.max_attempts == original_max + 1

    audit_row = (
        db_session.query(AuditLogORM)
        .filter(
            AuditLogORM.company_id == company_id,
            AuditLogORM.actor_user_id == admin_user.id,
            AuditLogORM.entity_type == "outbox_message",
            AuditLogORM.entity_id == msg.id,
            AuditLogORM.action == "OUTBOX_RETRY",
        )
        .order_by(AuditLogORM.created_at.desc())
        .first()
    )
    assert audit_row is not None
    assert audit_row.reason == "manual retry from reports"
    assert audit_row.before["status"] == "FAILED"
    assert audit_row.after["status"] == "PENDING"


def test_outbox_admin_bulk_retry_and_retry_audits(
    client_admin_real_uow,
    db_session,
    company_id,
    admin_user,
):
    project = _create_project(
        db_session,
        company_id=company_id,
        name=f"Outbox Bulk Retry Project {uuid.uuid4().hex[:8]}",
    )
    journal_id = _create_journal(client_admin_real_uow, project_id=project.id)
    ready_resp = client_admin_real_uow.post(f"/api/v1/admin/journals/{journal_id}/mark-ready")
    assert ready_resp.status_code == 200, ready_resp.text
    send_resp = client_admin_real_uow.post(
        f"/api/v1/admin/journals/{journal_id}/send",
        json={
            "email_to": "ops1@example.com",
            "whatsapp_to": "+15551112222",
            "send_email": True,
            "send_whatsapp": True,
        },
    )
    assert send_resp.status_code == 200, send_resp.text

    journal_uuid = uuid.UUID(journal_id)
    messages = (
        db_session.query(OutboxMessageORM)
        .filter(
            OutboxMessageORM.company_id == company_id,
            OutboxMessageORM.correlation_id == journal_uuid,
        )
        .order_by(OutboxMessageORM.created_at.asc())
        .all()
    )
    assert len(messages) >= 2

    failed_msg, sent_msg = messages[0], messages[1]
    failed_msg.status = OutboxStatus.FAILED
    failed_msg.delivery_status = DeliveryStatus.FAILED
    failed_msg.attempts = failed_msg.max_attempts
    failed_msg.last_error = "provider timeout"
    sent_msg.status = OutboxStatus.SENT
    db_session.add_all([failed_msg, sent_msg])
    db_session.commit()

    retry_resp = client_admin_real_uow.post(
        "/api/v1/admin/outbox/retry-failed",
        json={
            "outbox_ids": [str(failed_msg.id), str(sent_msg.id)],
            "reason": "operations_center_bulk_retry",
        },
    )
    assert retry_resp.status_code == 200, retry_resp.text
    body = retry_resp.json()
    assert body["total_messages"] == 2
    assert body["successful_messages"] == 1
    assert body["failed_messages"] == 0
    assert body["skipped_messages"] == 1
    by_id = {item["outbox_id"]: item for item in body["items"]}
    assert by_id[str(failed_msg.id)]["status"] == "retried"
    assert by_id[str(failed_msg.id)]["item"]["status"] == "PENDING"
    assert by_id[str(sent_msg.id)]["status"] == "skipped"

    db_session.refresh(failed_msg)
    assert failed_msg.status == OutboxStatus.PENDING
    assert failed_msg.delivery_status == DeliveryStatus.PENDING
    assert failed_msg.last_error is None

    audits_resp = client_admin_real_uow.get(
        "/api/v1/admin/outbox/retry-audits",
        params={"limit": 10},
    )
    assert audits_resp.status_code == 200, audits_resp.text
    audits = audits_resp.json()["items"]
    assert any(item["outbox_id"] == str(failed_msg.id) for item in audits)
    matching = next(item for item in audits if item["outbox_id"] == str(failed_msg.id))
    assert matching["reason"] == "operations_center_bulk_retry"
    assert matching["before_status"] == "FAILED"
    assert matching["after_status"] == "PENDING"

    audit_row = (
        db_session.query(AuditLogORM)
        .filter(
            AuditLogORM.company_id == company_id,
            AuditLogORM.actor_user_id == admin_user.id,
            AuditLogORM.entity_type == "outbox_message",
            AuditLogORM.entity_id == failed_msg.id,
            AuditLogORM.action == "OUTBOX_RETRY",
        )
        .order_by(AuditLogORM.created_at.desc())
        .first()
    )
    assert audit_row is not None
    assert audit_row.reason == "operations_center_bulk_retry"


def test_outbox_admin_retry_sent_message_returns_422(
    client_admin_real_uow,
    db_session,
    company_id,
):
    project = _create_project(
        db_session,
        company_id=company_id,
        name=f"Outbox Retry Sent Project {uuid.uuid4().hex[:8]}",
    )
    journal_id = _create_journal(client_admin_real_uow, project_id=project.id)
    ready_resp = client_admin_real_uow.post(
        f"/api/v1/admin/journals/{journal_id}/mark-ready"
    )
    assert ready_resp.status_code == 200, ready_resp.text
    send_resp = client_admin_real_uow.post(
        f"/api/v1/admin/journals/{journal_id}/send",
        json={
            "email_to": "client@example.com",
            "send_email": True,
            "send_whatsapp": False,
        },
    )
    assert send_resp.status_code == 200, send_resp.text

    journal_uuid = uuid.UUID(journal_id)
    msg = (
        db_session.query(OutboxMessageORM)
        .filter(
            OutboxMessageORM.company_id == company_id,
            OutboxMessageORM.correlation_id == journal_uuid,
            OutboxMessageORM.channel == OutboxChannel.EMAIL,
        )
        .order_by(OutboxMessageORM.created_at.desc())
        .first()
    )
    assert msg is not None
    msg.status = OutboxStatus.SENT
    db_session.add(msg)
    db_session.commit()

    retry_resp = client_admin_real_uow.post(
        f"/api/v1/admin/outbox/{msg.id}/retry",
        json={"reason": "must fail"},
    )
    assert retry_resp.status_code == 422, retry_resp.text
    assert retry_resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_outbox_admin_get_not_found(client_admin_real_uow):
    missing_id = uuid.uuid4()
    resp = client_admin_real_uow.get(f"/api/v1/admin/outbox/{missing_id}")
    assert resp.status_code == 404, resp.text
    assert resp.json()["error"]["code"] == "NOT_FOUND"

    retry_resp = client_admin_real_uow.post(
        f"/api/v1/admin/outbox/{missing_id}/retry",
        json={"reason": "missing"},
    )
    assert retry_resp.status_code == 404, retry_resp.text
    assert retry_resp.json()["error"]["code"] == "NOT_FOUND"


def test_outbox_admin_endpoints_forbidden_for_installer(client_installer):
    list_resp = client_installer.get("/api/v1/admin/outbox")
    assert list_resp.status_code == 403, list_resp.text
    assert list_resp.json()["error"]["code"] == "FORBIDDEN"

    summary_resp = client_installer.get("/api/v1/admin/outbox/summary")
    assert summary_resp.status_code == 403, summary_resp.text
    assert summary_resp.json()["error"]["code"] == "FORBIDDEN"

    webhook_summary_resp = client_installer.get("/api/v1/admin/outbox/webhook-signals/summary")
    assert webhook_summary_resp.status_code == 403, webhook_summary_resp.text
    assert webhook_summary_resp.json()["error"]["code"] == "FORBIDDEN"

    webhook_list_resp = client_installer.get("/api/v1/admin/outbox/webhook-signals")
    assert webhook_list_resp.status_code == 403, webhook_list_resp.text
    assert webhook_list_resp.json()["error"]["code"] == "FORBIDDEN"

    retry_audits_resp = client_installer.get("/api/v1/admin/outbox/retry-audits")
    assert retry_audits_resp.status_code == 403, retry_audits_resp.text
    assert retry_audits_resp.json()["error"]["code"] == "FORBIDDEN"

    get_resp = client_installer.get(f"/api/v1/admin/outbox/{uuid.uuid4()}")
    assert get_resp.status_code == 403, get_resp.text
    assert get_resp.json()["error"]["code"] == "FORBIDDEN"

    retry_resp = client_installer.post(
        f"/api/v1/admin/outbox/{uuid.uuid4()}/retry",
        json={"reason": "forbidden"},
    )
    assert retry_resp.status_code == 403, retry_resp.text
    assert retry_resp.json()["error"]["code"] == "FORBIDDEN"

    bulk_retry_resp = client_installer.post(
        "/api/v1/admin/outbox/retry-failed",
        json={"outbox_ids": [str(uuid.uuid4())], "reason": "forbidden"},
    )
    assert bulk_retry_resp.status_code == 403, bulk_retry_resp.text
    assert bulk_retry_resp.json()["error"]["code"] == "FORBIDDEN"
