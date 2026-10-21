import base64
import json
from datetime import timedelta
from uuid import UUID, uuid4
from unittest.mock import Mock

import pytest
from Crypto.Cipher import AES
from pydantic import SecretStr
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.modules.accounting.application.approval_email import deliver, KIND, CODE_KIND
from app.modules.accounting.infrastructure.approval_models import CommercialApprovalORM as Approval
from app.modules.accounting.infrastructure.models import CommercialContractORM, CommercialPriceVersionORM, CommercialPriceItemORM, CommercialContractTermsORM
from app.modules.audit.infrastructure.models import AuditLogORM
from app.modules.earnings.infrastructure.models import CompletedWorkORM
from app.modules.identity.infrastructure.models import AdminProfileORM
from app.modules.outbox.infrastructure.models import OutboxMessageORM
from app.modules.rates.application.approval_email import email_settings, UnavailableInvitation
from app.modules.rates.infrastructure.models import InstallerRateORM
from app.shared.infrastructure.db.base import utcnow
from tests.integration.test_commercial_drafts import owner_client, contract_body, contract, price_body, create_price, create_contract, URL
from tests.integration.test_commercial_contract_terms import terms_body, save

PUBLIC = "/api/v1/public/commercial-approvals"
KEY = b"commercial-isolated-test-only-key"[:32]


@pytest.fixture(autouse=True)
def isolation(db_session, company_id, monkeypatch):
    import os
    assert os.environ.get("APP_ENV") == "test"
    assert db_session.scalar(text("SELECT current_database()")).endswith("_tests")
    monkeypatch.setattr(settings, "EMAIL_ENABLED", True)
    monkeypatch.setattr(settings, "PUBLIC_APP_BASE_URL", "https://commercial.example.com")
    monkeypatch.setattr(email_settings, "FACTORY_APPROVAL_EMAIL_KEY", SecretStr(base64.b64encode(KEY).decode()))
    yield
    db_session.rollback()
    db_session.execute(text("SET LOCAL session_replication_role = 'replica'"))
    for model in (Approval, CommercialContractTermsORM, CommercialPriceItemORM, CommercialPriceVersionORM, CommercialContractORM):
        db_session.execute(delete(model).where(model.company_id == company_id))
    db_session.commit()


@pytest.fixture()
def prepared(owner_client, contract, terms_body, price_body):
    terms = save(owner_client, contract, terms_body)
    price = create_price(owner_client, contract, price_body)
    response = owner_client.post('/api/v1/admin/price-lists/factory/contact', json={
        "factory_name": "Synthetic factory", "recipient_name": "Factory Test Representative",
        "recipient_email": "factory@example.com", "authority_reference": "Synthetic OWNER approval",
        "expected_contact_id": None})
    assert response.status_code == 200, response.text
    candidate = owner_client.get(f'{URL}/{contract["id"]}/approval-preview', params={"terms_id": terms["id"], "price_id": price["id"]})
    assert candidate.status_code == 200, candidate.text
    return {"request_id": str(uuid4()), "terms_id": terms["id"], "price_id": price["id"],
            "factory_contact_id": response.json()["id"], "snapshot_hash": candidate.json()["snapshot_hash"]}


def path(contract):
    return f'{URL}/{contract["id"]}/approvals'


def unpack(db_session, approval_id, kind):
    db_session.expire_all()
    messages = db_session.scalars(select(OutboxMessageORM).order_by(OutboxMessageORM.created_at.desc())).all()
    msg = next(row for row in messages if row.payload.get("approval_id") == approval_id and row.payload.get("kind") == kind)
    sealed = base64.b64decode(msg.payload["sealed_commercial"])
    cipher = AES.new(KEY, AES.MODE_GCM, nonce=sealed[:16])
    cipher.update(f'{kind}:{msg.company_id}:{approval_id}'.encode())
    return json.loads(cipher.decrypt_and_verify(sealed[32:], sealed[16:32])), msg


def invite(client, contract, prepared, db_session):
    result = client.post(path(contract), json=prepared)
    assert result.status_code == 200, result.text
    data, message = unpack(db_session, result.json()["id"], KIND)
    assert data["token"] not in result.text and data["token"] not in json.dumps(message.payload)
    assert "confirmation_url" not in result.json()
    return result.json(), data["token"]


def decision(client, token, db_session, invitation):
    preview = client.post(PUBLIC + '/preview', json={"token": token})
    assert preview.status_code == 200, preview.text
    code = client.post(PUBLIC + '/request-code', json={"token": token})
    assert code.status_code == 200, code.text
    data, _ = unpack(db_session, invitation["id"], CODE_KIND)
    return {"token": token, "snapshot_hash": preview.json()["snapshot_hash"],
        "terms_version": preview.json()["snapshot"]["terms"]["version"],
        "price_version": preview.json()["snapshot"]["price"]["version"],
        "signer_name": "Factory Test Representative", "accepted": True, "verification_code": data["code"]}


def test_full_chain_exact_pair_no_financial_effect(owner_client, contract, prepared, db_session, company_id, price_body):
    before = [db_session.scalar(select(func.count()).select_from(model)) for model in (InstallerRateORM, CompletedWorkORM)]
    invitation, token = invite(owner_client, contract, prepared, db_session)
    assert owner_client.post(path(contract), json=prepared).json() == invitation
    assert owner_client.get(PUBLIC + '/confirm').status_code == 405
    body = decision(owner_client, token, db_session, invitation)
    assert owner_client.post(PUBLIC + '/confirm', json={**body, "price_version": 99}).status_code == 409
    assert owner_client.post(PUBLIC + '/confirm', json={**body, "accepted": False}).status_code == 422
    result = owner_client.post(PUBLIC + '/confirm', json=body)
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "CONFIRMED" and not result.json()["usable_for_billing"]
    assert result.json()["snapshot"]["is_demo"]
    assert owner_client.post(PUBLIC + '/confirm', json=body).json() == result.json()
    assert owner_client.post(PUBLIC + '/confirm', json={**body, "signer_name": "Different name"}).status_code == 409
    assert owner_client.post(path(contract) + '/' + invitation["id"] + '/revoke', json={"reason": "Not allowed"}).status_code == 409
    assert owner_client.post(path(contract), json={**prepared, "request_id": str(uuid4())}).status_code == 409
    newer = {**price_body, "request_id": str(uuid4()), "expected_latest_version": 1, "reason": "Amendment"}
    create_price(owner_client, contract, newer)
    assert owner_client.post(PUBLIC + '/preview', json={"token": token}).json() == result.json()
    history = owner_client.get(path(contract)).json()
    assert history["items"][0]["status"] == "CONFIRMED"
    assert history["items"][0]["price_version"] == 1
    assert [db_session.scalar(select(func.count()).select_from(model)) for model in (InstallerRateORM, CompletedWorkORM)] == before
    assert db_session.scalar(select(func.count()).select_from(AuditLogORM).where(
        AuditLogORM.company_id == company_id, AuditLogORM.entity_type == "COMMERCIAL_APPROVAL", AuditLogORM.action == "CONFIRM")) == 1


@pytest.mark.parametrize("change", ["terms", "price", "contact", "revoke", "expired"])
def test_pending_invalidated(owner_client, contract, prepared, db_session, terms_body, price_body, change, monkeypatch):
    invitation, token = invite(owner_client, contract, prepared, db_session)
    body = decision(owner_client, token, db_session, invitation)
    if change == "terms":
        save(owner_client, contract, {**terms_body, "request_id": str(uuid4()), "expected_latest_version": 1})
    elif change == "price":
        create_price(owner_client, contract, {**price_body, "request_id": str(uuid4()), "expected_latest_version": 1})
    elif change == "contact":
        result = owner_client.post('/api/v1/admin/price-lists/factory/contact/revoke', json={
            "expected_contact_id": prepared["factory_contact_id"], "reason": "Authority revoked"})
        assert result.status_code == 200
    elif change == "revoke":
        assert owner_client.post(path(contract) + '/' + invitation["id"] + '/revoke', json={"reason": "Cancelled"}).status_code == 200
    else:
        monkeypatch.setattr("app.modules.accounting.application.approval_service.utcnow", lambda: utcnow() + timedelta(days=8))
    assert owner_client.post(PUBLIC + '/confirm', json=body).status_code in (404, 409)
    assert owner_client.post(PUBLIC + '/request-code', json={"token": token}).status_code in (404, 409)
    _, message = unpack(db_session, invitation["id"], KIND)
    with pytest.raises(UnavailableInvitation):
        deliver(message, Mock())


def test_mailbox_attempts_replacement_and_delivery(owner_client, contract, prepared, db_session):
    invitation, token = invite(owner_client, contract, prepared, db_session)
    _, message = unpack(db_session, invitation["id"], KIND)
    sender = Mock()
    deliver(message, sender)
    assert sender.send.call_args.kwargs["to_email"] == "factory@example.com"
    assert '/commercial-approval#' in sender.send.call_args.kwargs["body_text"]
    assert 'TEST ONLY' in sender.send.call_args.kwargs["body_text"]
    body = decision(owner_client, token, db_session, invitation)
    _, message = unpack(db_session, invitation["id"], CODE_KIND)
    deliver(message, sender)
    assert body["verification_code"] in sender.send.call_args.kwargs["body_text"]
    assert owner_client.post(PUBLIC + '/request-code', json={"token": token}).status_code == 429
    wrong = "000000" if body["verification_code"] != "000000" else "999999"
    for _ in range(5):
        assert owner_client.post(PUBLIC + '/confirm', json={**body, "verification_code": wrong}).status_code == 403
    assert owner_client.post(PUBLIC + '/confirm', json=body).status_code == 403
    db_session.expire_all()
    assert db_session.get(Approval, UUID(invitation["id"])).mailbox_attempts == 5
    replacement, _ = invite(owner_client, contract, {**prepared, "request_id": str(uuid4())}, db_session)
    assert replacement["id"] != invitation["id"]
    assert owner_client.post(PUBLIC + '/preview', json={"token": token}).status_code == 404


def test_isolation_permissions_and_idempotency(owner_client, contract, prepared, db_session, admin_user, contract_body):
    invitation, _ = invite(owner_client, contract, prepared, db_session)
    assert owner_client.post(path(contract), json={**prepared, "expires_in_hours": 1}).status_code == 409
    assert owner_client.post(path(contract), json={**prepared, "recipient_email": "self@example.com"}).status_code == 422
    other = create_contract(owner_client, {**contract_body, "request_id": str(uuid4()), "reference": "OTHER"})
    assert owner_client.get(path(other) + '/' + invitation["id"]).status_code == 404
    assert owner_client.post(path(other), json={**prepared, "request_id": str(uuid4())}).status_code == 404
    profile = db_session.scalar(select(AdminProfileORM).where(AdminProfileORM.user_id == admin_user.id))
    profile.admin_scope = "OPERATIONS"
    db_session.commit()
    assert owner_client.get(path(contract)).status_code == 403
    assert owner_client.post(path(contract), json={**prepared, "request_id": str(uuid4())}).status_code == 403


def test_database_evidence_guards(owner_client, contract, prepared, db_session):
    invitation, token = invite(owner_client, contract, prepared, db_session)
    queries = [
        ("UPDATE commercial_approvals SET snapshot_hash=repeat('a',64) WHERE id=:id", invitation["id"]),
        ("DELETE FROM commercial_approvals WHERE id=:id", invitation["id"]),
        ("UPDATE commercial_price_versions SET reason='changed' WHERE id=:id", prepared["price_id"]),
        ("UPDATE commercial_price_items SET unit_price_ex_vat=1 WHERE price_version_id=:id", prepared["price_id"]),
    ]
    for sql, ident in queries:
        with pytest.raises(IntegrityError), db_session.begin_nested():
            db_session.execute(text(sql), {"id": ident})
    body = decision(owner_client, token, db_session, invitation)
    assert owner_client.post(PUBLIC + '/confirm', json=body).status_code == 200
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.execute(text("UPDATE commercial_approvals SET confirmed_name='altered' WHERE id=:id"), {"id": invitation["id"]})


def test_failed_audit_rolls_back_invitation_and_outbox(owner_client, contract, prepared, db_session, monkeypatch):
    before = db_session.scalar(select(func.count()).select_from(OutboxMessageORM))
    def fail(*args, **kwargs):
        raise RuntimeError("Synthetic audit failure")
    monkeypatch.setattr("app.modules.accounting.application.approval_service.AuditService.add", fail)
    assert owner_client.post(path(contract), json=prepared).status_code == 500
    assert db_session.scalar(select(func.count()).select_from(Approval)) == 0
    assert db_session.scalar(select(func.count()).select_from(OutboxMessageORM)) == before


@pytest.mark.parametrize("field,value", [("snapshot_hash", "b" * 64), ("factory_contact_id", str(uuid4()))])
def test_stale_review_cannot_be_sent(owner_client, contract, prepared, db_session, field, value):
    assert owner_client.post(path(contract), json={**prepared, field: value}).status_code == 409
    assert db_session.scalar(select(func.count()).select_from(Approval)) == 0


def test_email_disabled_is_atomic(owner_client, contract, prepared, db_session, monkeypatch):
    monkeypatch.setattr(settings, "EMAIL_ENABLED", False)
    result = owner_client.post(path(contract), json=prepared)
    assert result.status_code in (400, 422), result.text
    assert db_session.scalar(select(func.count()).select_from(Approval)) == 0


def test_demo_cannot_be_sent_as_real(owner_client, contract, prepared, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    assert owner_client.post(path(contract), json=prepared).status_code == 409


def test_expired_code_and_foreign_token(owner_client, contract, prepared, db_session, monkeypatch):
    invitation, token = invite(owner_client, contract, prepared, db_session)
    body = decision(owner_client, token, db_session, invitation)
    assert owner_client.post(PUBLIC + '/preview', json={"token": "Z" * 43}).status_code == 404
    monkeypatch.setattr("app.modules.accounting.application.approval_service.utcnow", lambda: utcnow() + timedelta(minutes=11))
    assert owner_client.post(PUBLIC + '/confirm', json=body).status_code == 403


def test_concurrent_same_request_has_one_invitation(owner_client, contract, prepared, db_session, admin_user):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from app.modules.accounting.application.approval_dto import IssueCommercialApproval
    from app.modules.accounting.application.approval_service import CommercialApprovalService
    from app.shared.infrastructure.db.uow_sqlalchemy import SqlAlchemyUnitOfWork
    barrier = Barrier(2)
    def issue():
        barrier.wait(timeout=20)
        with SqlAlchemyUnitOfWork() as uow:
            return CommercialApprovalService.issue(uow, admin_user, UUID(contract["id"]), IssueCommercialApproval(**prepared)).id
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: issue(), range(2)))
    assert results[0] == results[1]
    assert db_session.scalar(select(func.count()).select_from(Approval)) == 1
