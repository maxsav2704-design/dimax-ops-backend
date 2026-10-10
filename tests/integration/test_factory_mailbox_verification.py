import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import Mock, patch
from uuid import UUID

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.modules.outbox.application.admin_service import _to_dto
from app.modules.outbox.infrastructure.models import OutboxMessageORM
from app.modules.outbox.infrastructure.repositories import OutboxRepository
from app.modules.rates.application.approval_dto import ConfirmApproval
from app.modules.rates.application.approval_email import CODE_KIND, UnavailableInvitation, deliver_code
from app.modules.rates.application.approval_service import FactoryPriceApprovalService
from app.modules.rates.application.approval_verification import VerificationRejected
from app.modules.rates.infrastructure.approval_models import FactoryPriceApprovalORM
from app.shared.infrastructure.db.base import utcnow
from app.shared.infrastructure.db.uow_sqlalchemy import SqlAlchemyUnitOfWork
from factory_mailbox_helpers import TEST_CODE
from test_factory_price_approvals_api import ADMIN, PUBLIC, approval_case, confirmation, preview
from test_factory_approval_email import isolated_email


def invitation(db_session, case):
    db_session.expire_all()
    return db_session.get(FactoryPriceApprovalORM, UUID(case["issued"]["invitation"]["id"]))


def messages(db_session, case):
    return list(db_session.scalars(select(OutboxMessageORM).where(
        OutboxMessageORM.payload["approval_id"].astext == case["issued"]["invitation"]["id"],
        OutboxMessageORM.payload["kind"].astext == CODE_KIND)))


def test_link_alone_never_confirms(client_raw, approval_case, db_session):
    data = preview(client_raw, approval_case).json()
    body = {"token": approval_case["token"], "expected_version": data["version"],
            "snapshot_hash": data["snapshot_hash"], "signer_name": "Someone with link", "accepted": True}
    assert client_raw.post(f"{PUBLIC}/confirm", json=body).status_code == 403
    assert client_raw.post(f"{PUBLIC}/confirm", json={**body, "verification_code": "123456"}).status_code == 403
    assert invitation(db_session, approval_case).confirmed_at is None


def test_mailbox_delivery_and_exact_decision_retry(client_raw, approval_case, db_session):
    body = confirmation(client_raw, approval_case)
    row = invitation(db_session, approval_case)
    message, = messages(db_session, approval_case)
    assert TEST_CODE not in row.mailbox_code_hash and TEST_CODE not in json.dumps(message.payload)
    assert approval_case["token"] not in json.dumps(message.payload)
    assert "sealed_code" not in _to_dto(message).model_dump_json()
    sender = Mock()
    deliver_code(message, sender)
    sent = sender.send.call_args.kwargs
    assert TEST_CODE in sent["body_text"] and TEST_CODE in sent["body_html"]
    assert sent["to_email"] == approval_case["body"]["recipient_email"]
    assert approval_case["token"] not in str(sent)
    confirmed = client_raw.post(f"{PUBLIC}/confirm", json=body)
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["mailbox_verified_at"] == confirmed.json()["confirmed_at"]
    with patch("app.modules.rates.application.approval_service.utcnow", return_value=utcnow() + timedelta(minutes=11)):
        assert client_raw.post(f"{PUBLIC}/confirm", json=body).json() == confirmed.json()
    assert client_raw.post(f"{PUBLIC}/confirm", json={**body, "verification_code": "000000"}).status_code == 403
    with pytest.raises(UnavailableInvitation):
        deliver_code(message, sender)


def test_failed_attempts_commit_and_resend_cannot_reset_budget(client_raw, approval_case, db_session):
    body = confirmation(client_raw, approval_case)
    wrong = {**body, "verification_code": "000000"}
    for count in range(1, 4):
        assert client_raw.post(f"{PUBLIC}/confirm", json=wrong).status_code == 403
        assert invitation(db_session, approval_case).mailbox_attempts == count
    now = utcnow() + timedelta(seconds=61)
    with patch("app.modules.rates.application.approval_service.utcnow", return_value=now):
        assert client_raw.post(f"{PUBLIC}/request-code", json={"token": body["token"]}).status_code == 200
    assert invitation(db_session, approval_case).mailbox_attempts == 3
    for _ in range(2):
        assert client_raw.post(f"{PUBLIC}/confirm", json=wrong).status_code == 403
    assert invitation(db_session, approval_case).mailbox_attempts == 5
    assert client_raw.post(f"{PUBLIC}/confirm", json=body).status_code == 403
    with patch("app.modules.rates.application.approval_service.utcnow", return_value=now + timedelta(minutes=2)):
        assert client_raw.post(f"{PUBLIC}/request-code", json={"token": body["token"]}).status_code == 429
    assert invitation(db_session, approval_case).confirmed_at is None


def test_expired_code_and_replaced_code_are_rejected(client_raw, approval_case, db_session):
    body = confirmation(client_raw, approval_case)
    message, = messages(db_session, approval_case)
    now = utcnow() + timedelta(minutes=11)
    with patch("app.modules.rates.application.approval_service.utcnow", return_value=now):
        assert client_raw.post(f"{PUBLIC}/confirm", json=body).status_code == 403
        with patch("app.modules.rates.application.approval_verification.secrets.randbelow", return_value=654321):
            assert client_raw.post(f"{PUBLIC}/request-code", json={"token": body["token"]}).status_code == 200
        assert client_raw.post(f"{PUBLIC}/confirm", json=body).status_code == 403
        assert client_raw.post(f"{PUBLIC}/confirm", json={**body, "verification_code": "654321"}).status_code == 200
    with pytest.raises(UnavailableInvitation):
        deliver_code(message, Mock())


def test_request_limits_and_unknown_links(client_raw, approval_case, db_session):
    assert client_raw.post(f"{PUBLIC}/request-code", json={"token": "z" * 43}).status_code == 404
    now = utcnow()
    for count in range(10):
        with patch("app.modules.rates.application.approval_service.utcnow", return_value=now + timedelta(minutes=2 * count)):
            response = client_raw.post(f"{PUBLIC}/request-code", json={"token": approval_case["token"]})
            assert response.status_code == 200, response.text
            assert response.headers["cache-control"] == "no-store"
            assert response.json()["status"] == "QUEUED"
            assert client_raw.post(f"{PUBLIC}/request-code", json={"token": approval_case["token"]}).status_code == 429
    with patch("app.modules.rates.application.approval_service.utcnow", return_value=now + timedelta(hours=1)):
        assert client_raw.post(f"{PUBLIC}/request-code", json={"token": approval_case["token"]}).status_code == 429
    assert invitation(db_session, approval_case).mailbox_requests == 10


@pytest.mark.parametrize("mode", ["revoke", "rotate", "expire", "recipient", "ciphertext", "locked"])
def test_unusable_challenges_are_not_sent(client, client_raw, approval_case, db_session, mode):
    body = confirmation(client_raw, approval_case)
    message, = messages(db_session, approval_case)
    base = f'{ADMIN}/{approval_case["price_list"]["id"]}/approvals'
    row = invitation(db_session, approval_case)
    if mode == "revoke":
        assert client.post(f'{base}/{row.id}/revoke', json={"reason": "Wrong contact"}).status_code == 200
    elif mode == "rotate":
        assert client.post(base, json=approval_case["body"]).status_code == 200
    elif mode == "expire":
        row.mailbox_requested_at = utcnow() - timedelta(minutes=11)
        row.mailbox_code_expires_at = utcnow() - timedelta(minutes=1)
        db_session.commit()
    elif mode == "locked":
        row.mailbox_attempts = 5
        db_session.commit()
    else:
        message.payload = {**message.payload, **({"to_email": "wrong@example.com"} if mode == "recipient" else {"sealed_code": "invalid"})}
        db_session.commit()
    sender = Mock()
    with pytest.raises(UnavailableInvitation):
        deliver_code(message, sender)
    sender.send.assert_not_called()
    if mode not in {"recipient", "ciphertext"}:
        assert client_raw.post(f"{PUBLIC}/confirm", json=body).status_code in {403, 404}


def test_enqueue_failure_and_disabled_mail_do_not_consume_request(client_raw, approval_case, db_session, monkeypatch):
    with patch.object(OutboxRepository, "enqueue", side_effect=RuntimeError("queue unavailable")):
        assert client_raw.post(f"{PUBLIC}/request-code", json={"token": approval_case["token"]}).status_code == 500
    row = invitation(db_session, approval_case)
    assert row.mailbox_requests == 0 and row.mailbox_code_hash is None
    monkeypatch.setattr(settings, "EMAIL_ENABLED", False)
    assert client_raw.post(f"{PUBLIC}/request-code", json={"token": approval_case["token"]}).status_code == 422
    assert invitation(db_session, approval_case).mailbox_requests == 0


def test_wrong_attempts_are_serialized_across_workers(client_raw, approval_case, db_session):
    body = ConfirmApproval.model_validate({**confirmation(client_raw, approval_case), "verification_code": "000000"})
    barrier = Barrier(2)
    def attempt():
        barrier.wait(timeout=15)
        with SqlAlchemyUnitOfWork() as uow:
            return FactoryPriceApprovalService.confirm(uow, body=body)
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(lambda _: attempt(), range(2)))
    assert all(isinstance(row, VerificationRejected) for row in result)
    assert invitation(db_session, approval_case).mailbox_attempts == 2


def test_code_cannot_confirm_another_invitation(client, client_raw, approval_case, db_session):
    body = confirmation(client_raw, approval_case)
    issued = client.post(f'{ADMIN}/{approval_case["price_list"]["id"]}/approvals', json=approval_case["body"]).json()
    token = issued["confirmation_url"].split("#")[1]
    assert client_raw.post(f"{PUBLIC}/confirm", json={**body, "token": token}).status_code == 403


def test_worker_redacts_smtp_errors_and_retries_once(client_raw, approval_case, db_session):
    from app.workers import outbox_worker
    body = confirmation(client_raw, approval_case)
    message, = messages(db_session, approval_case)
    outbox_worker.email_sender.send.side_effect = RuntimeError(f'{body["token"]} {TEST_CODE}')
    assert outbox_worker.run_once() == 0
    db_session.refresh(message)
    assert message.status.value == "PENDING" and message.attempts == 1
    assert TEST_CODE not in message.last_error and body["token"] not in message.last_error
    outbox_worker.email_sender.send.side_effect = None
    assert outbox_worker.run_once() == 1
    assert outbox_worker.run_once() == 0
    assert preview(client_raw, approval_case).json()["status"] == "PENDING"


@pytest.mark.skipif(os.getenv("DIMAX_FACTORY_MAILPIT") != "1", reason="Requires isolated Mailpit")
def test_real_mailpit_code_confirms_only_after_explicit_submission(client_raw, approval_case, db_session, monkeypatch):
    from app.integrations.email.smtp_sender import SmtpEmailSender
    from app.workers import outbox_worker
    from test_journal_mailpit_acceptance import _mailpit
    assert settings.SMTP_HOST == "mailpit" and settings.SMTP_PORT == 1025
    row = invitation(db_session, approval_case)
    row.recipient_email = f"mailbox-{row.id}@example.com"
    db_session.commit()
    body = confirmation(client_raw, approval_case)
    recipient = row.recipient_email
    monkeypatch.setattr(outbox_worker, "email_sender", SmtpEmailSender())
    try:
        assert outbox_worker.run_once() == 1
        matches = [m for m in json.loads(_mailpit("messages?limit=200"))["messages"]
                   if any(r["Address"] == recipient for r in m["To"])]
        assert len(matches) == 1
        message = json.loads(_mailpit(f'message/{matches[0]["ID"]}'))
        assert TEST_CODE in message["Text"] and TEST_CODE in message["HTML"]
        assert body["token"] not in message["Text"]
        assert preview(client_raw, approval_case).json()["status"] == "PENDING"
        assert client_raw.post(f"{PUBLIC}/confirm", json=body).json()["status"] == "CONFIRMED"
    finally:
        matches = [m for m in json.loads(_mailpit("messages?limit=200"))["messages"]
                   if any(r["Address"] == recipient for r in m["To"])]
        if matches:
            _mailpit("messages", method="DELETE", body={"IDs": [m["ID"] for m in matches]})
