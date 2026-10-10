import base64
import json
import os
from datetime import timedelta
from unittest.mock import Mock, patch
from urllib.parse import urlsplit
from uuid import UUID

import pytest
from pydantic import SecretStr
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.modules.outbox.application.admin_service import _to_dto
from app.modules.outbox.infrastructure.models import OutboxMessageORM
from app.modules.outbox.infrastructure.repositories import OutboxRepository
from app.modules.rates.application.approval_email import email_settings
from app.modules.rates.infrastructure.approval_models import FactoryPriceApprovalORM
from app.shared.infrastructure.db.base import utcnow
from app.workers import outbox_worker
from test_factory_price_approvals_api import ADMIN, PUBLIC, approval_case, confirmation


@pytest.fixture(autouse=True)
def isolated_email(monkeypatch, db_session, company_id):
    assert db_session.get_bind().url.database == "dimax_acceptance_tests"
    monkeypatch.setattr(email_settings, "FACTORY_APPROVAL_EMAIL_KEY", SecretStr(base64.b64encode(bytes(range(32))).decode()))
    monkeypatch.setattr(settings, "PUBLIC_APP_BASE_URL", "https://dimax.example.org")
    monkeypatch.setattr(settings, "EMAIL_ENABLED", True)
    class ScopedOutbox(OutboxRepository):
        def lock_next_batch(self, *, company_id=None, limit=20):
            return super().lock_next_batch(company_id=scope, limit=limit)
    scope = company_id
    monkeypatch.setattr(outbox_worker, "OutboxRepository", ScopedOutbox)
    monkeypatch.setattr(outbox_worker, "SessionLocal", sessionmaker(bind=db_session.get_bind()))
    monkeypatch.setattr(outbox_worker, "email_sender", Mock())


def queued(client, case, db_session):
    result = client.post(f'{ADMIN}/{case["price_list"]["id"]}/approvals', json={**case["body"], "send_email": True})
    assert result.status_code == 200, result.text
    data = result.json()
    return data, db_session.get(OutboxMessageORM, UUID(data["email_outbox_id"]))


def test_optional_atomic_sealed_delivery(client, approval_case, db_session):
    assert approval_case["issued"]["email_outbox_id"] is None
    data, row = queued(client, approval_case, db_session)
    token = urlsplit(data["confirmation_url"]).fragment
    assert token not in json.dumps(row.payload)
    assert row.correlation_id is None
    assert "sealed_link" not in _to_dto(row).model_dump_json()
    assert outbox_worker.run_once() == 1
    assert outbox_worker.run_once() == 0
    sent = outbox_worker.email_sender.send.call_args.kwargs
    assert sent["to_email"] == approval_case["body"]["recipient_email"]
    assert data["confirmation_url"] in sent["body_text"]
    assert data["confirmation_url"] in sent["body_html"]
    assert 'Opening this link does not confirm' in sent["body_text"]
    assert client.get(f'{ADMIN}/{approval_case["price_list"]["id"]}').json()["status"] == "DRAFT"


@pytest.mark.parametrize("mode", ["disabled", "key", "http", "localhost", "private_ip", "localhost_dot", "bad_port", "malformed"])
def test_invalid_delivery_configuration_keeps_old_link(client, approval_case, monkeypatch, mode):
    if mode == "disabled": monkeypatch.setattr(settings, "EMAIL_ENABLED", False)
    elif mode == "key": monkeypatch.setattr(email_settings, "FACTORY_APPROVAL_EMAIL_KEY", SecretStr(""))
    else: monkeypatch.setattr(settings, "PUBLIC_APP_BASE_URL", {"http": "http://dimax.example.org", "localhost": "https://localhost", "private_ip": "https://192.168.1.2", "localhost_dot": "https://localhost.", "bad_port": "https://dimax.example.org:wrong", "malformed": "https://["}[mode])
    result = client.post(f'{ADMIN}/{approval_case["price_list"]["id"]}/approvals', json={**approval_case["body"], "send_email": True})
    assert result.status_code == 422, result.text
    assert client.post(f"{PUBLIC}/preview", json={"token": approval_case["token"]}).status_code == 200


@pytest.mark.parametrize("mode", ["revoke", "expire", "rotate", "confirm", "recipient", "ciphertext"])
def test_stale_or_tampered_messages_are_not_sent(client, approval_case, db_session, mode):
    data, row = queued(client, approval_case, db_session)
    approval_id = data["invitation"]["id"]
    base = f'{ADMIN}/{approval_case["price_list"]["id"]}'
    if mode == "revoke":
        assert client.post(f'{base}/approvals/{approval_id}/revoke', json={"reason": "Wrong contact"}).status_code == 200
    elif mode == "rotate":
        assert client.post(f"{base}/approvals", json=approval_case["body"]).status_code == 200
    elif mode == "confirm":
        case = {**approval_case, "token": urlsplit(data["confirmation_url"]).fragment}
        assert client.post(f"{PUBLIC}/confirm", json=confirmation(client, case)).status_code == 200
    elif mode == "expire":
        invitation = db_session.get(FactoryPriceApprovalORM, UUID(approval_id))
        invitation.created_at = utcnow() - timedelta(days=2)
        invitation.expires_at = utcnow() - timedelta(days=1)
        db_session.commit()
    else:
        row.payload = {**row.payload, **({"to_email": "other@example.org"} if mode == "recipient" else {"sealed_link": "corrupted"})}
        db_session.commit()
    assert outbox_worker.run_once() == 0
    db_session.refresh(row)
    assert row.status.value == "FAILED" and row.attempts == row.max_attempts
    outbox_worker.email_sender.send.assert_not_called()
    assert outbox_worker.run_once() == 0


def test_smtp_failure_is_redacted_and_retryable(client, approval_case, db_session):
    data, row = queued(client, approval_case, db_session)
    token = urlsplit(data["confirmation_url"]).fragment
    outbox_worker.email_sender.send.side_effect = RuntimeError(data["confirmation_url"])
    assert outbox_worker.run_once() == 0
    db_session.refresh(row)
    assert row.status.value == "PENDING" and row.attempts == 1 and token not in row.last_error
    outbox_worker.email_sender.send.side_effect = None
    assert outbox_worker.run_once() == 1


def test_enqueue_failure_rolls_back_invitation_rotation(client, approval_case):
    with patch.object(OutboxRepository, "enqueue", side_effect=RuntimeError("queue unavailable")):
        result = client.post(f'{ADMIN}/{approval_case["price_list"]["id"]}/approvals', json={**approval_case["body"], "send_email": True})
    assert result.status_code == 500
    assert client.post(f"{PUBLIC}/preview", json={"token": approval_case["token"]}).status_code == 200


@pytest.mark.skipif(os.getenv("DIMAX_FACTORY_MAILPIT") != "1", reason="Requires isolated Mailpit")
def test_actual_mailpit_multipart_delivery(client, approval_case, db_session, monkeypatch, company_id):
    from app.integrations.email.smtp_sender import SmtpEmailSender
    from test_journal_mailpit_acceptance import _mailpit
    assert settings.SMTP_HOST == "mailpit" and settings.SMTP_PORT == 1025
    case = {**approval_case, "body": {**approval_case["body"], "recipient_email": f"factory-{company_id}@example.com"}}
    data, _ = queued(client, case, db_session)
    monkeypatch.setattr(outbox_worker, "email_sender", SmtpEmailSender())
    try:
        assert outbox_worker.run_once() == 1
        matches = [m for m in json.loads(_mailpit("messages?limit=200"))["messages"]
                   if any(r["Address"] == case["body"]["recipient_email"] for r in m["To"])]
        assert len(matches) == 1
        message = json.loads(_mailpit(f'message/{matches[0]["ID"]}'))
        assert data["confirmation_url"] in message["Text"]
        assert data["confirmation_url"] in message["HTML"]
    finally:
        matches = [m for m in json.loads(_mailpit("messages?limit=200"))["messages"]
                   if any(r["Address"] == case["body"]["recipient_email"] for r in m["To"])]
        if matches:
            _mailpit("messages", method="DELETE", body={"IDs": [m["ID"] for m in matches]})
