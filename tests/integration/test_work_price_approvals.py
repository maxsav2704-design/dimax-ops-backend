import runpy
import json
import re
from datetime import timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.modules.audit.infrastructure.models import AuditLogORM
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.earnings.infrastructure.models import CompletedWorkORM
from app.modules.addons.infrastructure.models import ProjectAddonFactORM
from app.modules.identity.infrastructure.models import AdminProfileORM
from app.modules.outbox.application.admin_service import _to_dto
from app.modules.outbox.infrastructure.models import OutboxMessageORM
from app.modules.outbox.infrastructure.repositories import OutboxRepository
from app.modules.sync.infrastructure.work_price_approval_model import WorkPriceApprovalORM
from app.modules.sync.application import work_price_approval_service as service
from app.shared.infrastructure.db.base import utcnow
from app.workers import outbox_worker
from test_factory_approval_email import isolated_email
from test_work_price_proposals import case, clean_test_proposals, missing, proposal_body

PUBLIC = "/api/v1/public/price-approvals/work"


@pytest.fixture(autouse=True)
def clean_invitations(db_session, company_id, clean_test_proposals, isolated_email):
    yield
    db_session.rollback()
    assert db_session.execute(text("SELECT current_database()")).scalar_one().endswith("_tests")
    db_session.execute(text("ALTER TABLE work_price_approvals DISABLE TRIGGER work_price_approval_guard"))
    db_session.execute(text("DELETE FROM work_price_approvals WHERE company_id=:cid"), {"cid": company_id})
    db_session.execute(text("ALTER TABLE work_price_approvals ENABLE TRIGGER work_price_approval_guard"))
    db_session.commit()


def prepare(case, db, client, kind="ADDON", channel="batch", legacy=False):
    row, proposals, _ = missing(case, db, kind, channel, legacy)
    proposal = client.post(proposals, json=proposal_body(client, proposals)).json()
    contact = client.get("/api/v1/admin/price-lists/factory/contact").json()
    url = f'/api/v1/admin/sync/work-price-proposals/{proposal["id"]}/invitations'
    body = {"request_id": str(uuid4()), "factory_contact_id": contact["id"], "proposal_hash": proposal["snapshot_hash"]}
    return row, proposals, proposal, url, body


def send(client, url, body):
    result = client.post(url, json=body)
    assert result.status_code == 200, result.text
    assert result.headers["cache-control"] == "no-store"
    assert outbox_worker.run_once() == 1
    sent = outbox_worker.email_sender.send.call_args.kwargs
    token = re.search(r"/work-price-approval#([A-Za-z0-9_-]{43})", sent["body_text"])[1]
    return result.json(), token


def confirmation(client, token):
    preview = client.post(PUBLIC + "/preview", json={"token": token})
    assert preview.status_code == 200, preview.text
    response = client.post(PUBLIC + "/request-code", json={"token": token})
    assert response.status_code == 200, response.text
    assert outbox_worker.run_once() == 1
    sent = outbox_worker.email_sender.send.call_args.kwargs
    assert token not in sent["body_text"] and token not in sent["body_html"]
    code = re.search(r"Confirmation code: ([0-9]{6})", sent["body_text"])[1]
    data = preview.json()
    return {"token": token, "expected_version": data["version"], "snapshot_hash": data["snapshot_hash"],
        "signer_name": "Factory Representative QA", "accepted": True, "verification_code": code}


@pytest.mark.parametrize("kind", ["DOOR", "ADDON"])
@pytest.mark.parametrize("channel", ["sync", "batch"])
@pytest.mark.parametrize("legacy", [False, True])
def test_independent_confirmation_never_accrues(case, db_session, client_admin_real_uow, client_raw, kind, channel, legacy):
    client = client_admin_real_uow
    row, _, proposal, url, body = prepare(case, db_session, client, kind, channel, legacy)
    original_payload = dict(row.payload)
    issued, token = send(client, url, body)
    assert token not in json.dumps(issued)
    assert client.post(url, json=body).json() == issued
    assert outbox_worker.run_once() == 0
    assert client.post(url, json={**body, "expires_in_hours": 1}).status_code == 409
    stored = db_session.get(OutboxMessageORM, UUID(issued["email_outbox_id"]))
    assert token not in json.dumps(stored.payload)
    assert "sealed_work_price" not in _to_dto(stored).model_dump_json()
    preview = client_raw.post(PUBLIC + "/preview", json={"token": token}).json()
    assert preview["status"] == "PENDING" and preview["work"]["proposal_id"] == proposal["id"]
    assert preview["work"]["quantity"] == proposal["scope"]["quantity"]
    assert "execution_evidence" not in json.dumps(preview)
    assert client_raw.post("/api/v1/public/price-approvals/preview", json={"token": token}).status_code == 404
    confirm = confirmation(client_raw, token)
    assert client_raw.post(PUBLIC + "/confirm", json={**confirm, "verification_code": None}).status_code == 403
    result = client_raw.post(PUBLIC + "/confirm", json=confirm)
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "CONFIRMED" and result.json()["affects_earnings"] is False
    assert client_raw.post(PUBLIC + "/confirm", json=confirm).json() == result.json()
    assert client_raw.post(PUBLIC + "/confirm", json={**confirm, "signer_name": "Another signer"}).status_code == 409
    assert client.post(url, json={**body, "request_id": str(uuid4())}).status_code == 409
    assert client.post(url + f'/{issued["id"]}/revoke', json={"reason": "Attempt to revoke decision"}).status_code == 409
    history = client.get(url).json()
    assert history["total"] == 1 and history["items"][0]["mailbox_verified_at"] is not None
    db_session.expire_all()
    assert row.payload == original_payload
    assert db_session.query(CompletedWorkORM).filter_by(company_id=case.company).count() == 0
    assert db_session.query(ProjectAddonFactORM).filter_by(company_id=case.company).count() == 0
    assert db_session.query(AuditLogORM).filter_by(company_id=case.company, entity_type="WORK_PRICE_APPROVAL", action="CONFIRM").count() == 1
    for sql in ("UPDATE work_price_approvals SET confirmed_name='Changed' WHERE id=:id",
                "DELETE FROM work_price_approvals WHERE id=:id"):
        with pytest.raises(DBAPIError):
            db_session.execute(text(sql), {"id": UUID(issued["id"])})
        db_session.rollback()


@pytest.mark.parametrize("change", ["contact", "revoke", "rotate", "proposal", "assignment", "door_version", "expire"])
def test_stale_invitation_blocks_confirmation_and_delivery(case, db_session, client_admin_real_uow, change, monkeypatch):
    client = client_admin_real_uow
    _, proposals, _, url, body = prepare(case, db_session, client, "DOOR")
    issued, token = send(client, url, body)
    confirm = confirmation(client, token)
    # Queue a second message, then invalidate the invitation before worker delivery.
    db_session.get(OutboxMessageORM, UUID(issued["email_outbox_id"])).status = "PENDING"
    db_session.commit()
    if change == "contact":
        assert client.post("/api/v1/admin/price-lists/factory/contact/revoke", json={
            "expected_contact_id": body["factory_contact_id"], "reason": "Representative no longer authorized"}).status_code == 200
    elif change == "revoke":
        assert client.post(url + f'/{issued["id"]}/revoke', json={"reason": "Invitation withdrawn"}).status_code == 200
    elif change == "rotate":
        assert client.post(url, json={**body, "request_id": str(uuid4())}).status_code == 200
    elif change == "proposal":
        assert client.post(proposals, json=proposal_body(client, proposals, rate="12.00")).status_code == 200
    elif change == "expire":
        future = utcnow() + timedelta(days=8)
        monkeypatch.setattr(service, "utcnow", lambda: future)
    else:
        door = db_session.get(DoorORM, case.door)
        if change == "assignment": door.installer_id = None
        else: door.version += 1
        db_session.commit()
    assert client.post(PUBLIC + "/confirm", json=confirm).status_code in (403, 404, 409)
    outbox_worker.email_sender.send.reset_mock()
    assert outbox_worker.run_once() == (1 if change == "rotate" else 0)
    assert db_session.query(CompletedWorkORM).filter_by(company_id=case.company).count() == 0


def test_mailbox_limits_and_snapshot_consent(case, db_session, client_admin_real_uow):
    client = client_admin_real_uow
    _, _, _, url, body = prepare(case, db_session, client)
    issued, token = send(client, url, body)
    confirm = confirmation(client, token)
    assert client.post(PUBLIC + "/request-code", json={"token": token}).status_code == 429
    assert client.post(PUBLIC + "/confirm", json={**confirm, "accepted": False}).status_code == 422
    assert client.post(PUBLIC + "/confirm", json={**confirm, "snapshot_hash": "a" * 64}).status_code == 409
    wrong = "000000" if confirm["verification_code"] != "000000" else "999999"
    for _ in range(5):
        assert client.post(PUBLIC + "/confirm", json={**confirm, "verification_code": wrong}).status_code == 403
    assert client.post(PUBLIC + "/confirm", json=confirm).status_code == 403
    assert client.post(PUBLIC + "/request-code", json={"token": token}).status_code == 429
    db_session.expire_all()
    assert db_session.get(WorkPriceApprovalORM, UUID(issued["id"])).mailbox_attempts == 5


def test_atomic_issue_and_nonempty_downgrade_guard(case, db_session, client_admin_real_uow, monkeypatch):
    client = client_admin_real_uow
    _, _, _, url, body = prepare(case, db_session, client)
    with patch.object(OutboxRepository, "enqueue", side_effect=RuntimeError("queue unavailable")):
        assert client.post(url, json=body).status_code == 500
    assert db_session.query(WorkPriceApprovalORM).filter_by(company_id=case.company).count() == 0
    assert client.post(url, json=body).status_code == 200
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    downgrade = runpy.run_path("alembic/versions/0073_work_price_approvals.py")["downgrade"]
    monkeypatch.setitem(downgrade.__globals__, "op", Operations(MigrationContext.configure(db_session.connection())))
    with pytest.raises(RuntimeError, match="history exists"):
        downgrade()
    db_session.rollback()


@pytest.mark.parametrize("scope,rates,expected", [("OWNER", True, 200), ("OPERATIONS", True, 200),
    ("OPERATIONS", False, 403), ("FINANCE", True, 403), ("VIEWER", True, 403), ("INSTALLER", False, 403)])
def test_live_roles_cannot_self_approve(case, db_session, client_admin_real_uow, client_raw, make_user, scope, rates, expected):
    from app.modules.identity.domain.enums import UserRole
    _, _, _, url, body = prepare(case, db_session, client_admin_real_uow)
    user = make_user(role=UserRole.INSTALLER if scope == "INSTALLER" else UserRole.ADMIN)
    if scope != "INSTALLER":
        profile = db_session.query(AdminProfileORM).filter_by(user_id=user.id).one()
        profile.admin_scope, profile.can_view_rates = scope, rates
        db_session.commit()
    login = client_raw.post("/api/v1/auth/login", json={"company_id": str(case.company),
        "email": user.email, "password": "secret123", "device_id": "work-price-invitation"})
    headers = {"Authorization": f'Bearer {login.json()["access_token"]}'}
    assert client_raw.post(url, json=body).status_code == 401
    assert client_raw.post(url, json=body, headers=headers).status_code == expected
    assert client_raw.get(url, headers=headers).status_code == expected


@pytest.mark.parametrize("tamper", ["recipient", "company", "ciphertext", "kind"])
def test_message_binding_and_secret_redaction(case, db_session, client_admin_real_uow, tamper):
    client = client_admin_real_uow
    _, _, _, url, body = prepare(case, db_session, client)
    result = client.post(url, json=body).json()
    row = db_session.get(OutboxMessageORM, UUID(result["email_outbox_id"]))
    if tamper == "company":
        # Preserve the worker tenant filter; make the authenticated ciphertext use a different identity.
        row.payload = {**row.payload, "approval_id": str(uuid4())}
    else:
        key, value = {"recipient": ("to_email", "other@example.org"), "ciphertext": ("sealed_work_price", "bad"),
            "kind": ("kind", "WORK_PRICE_MAILBOX_CODE")}[tamper]
        row.payload = {**row.payload, key: value}
    db_session.commit()
    outbox_worker.email_sender.send.reset_mock()
    assert outbox_worker.run_once() == 0
    outbox_worker.email_sender.send.assert_not_called()
    db_session.refresh(row)
    assert row.status.value == "FAILED"


@pytest.mark.parametrize("change", ["disabled", "insecure_url", "contact", "hash", "extra_rate"])
def test_invalid_issue_keeps_original_invitation(case, db_session, client_admin_real_uow, monkeypatch, change):
    from app.core.config import settings
    client = client_admin_real_uow
    _, _, _, url, body = prepare(case, db_session, client)
    _, token = send(client, url, body)
    body = {**body, "request_id": str(uuid4())}
    if change == "disabled": monkeypatch.setattr(settings, "EMAIL_ENABLED", False)
    elif change == "insecure_url": monkeypatch.setattr(settings, "PUBLIC_APP_BASE_URL", "http://localhost")
    elif change == "contact": body["factory_contact_id"] = str(uuid4())
    elif change == "hash": body["proposal_hash"] = "a" * 64
    else: body["rate"] = "1"
    assert client.post(url, json=body).status_code in (409, 422)
    assert client.post(PUBLIC + "/preview", json={"token": token}).status_code == 200
    assert db_session.query(WorkPriceApprovalORM).filter_by(company_id=case.company).count() == 1


def test_foreign_company_cannot_read_issue_or_revoke(case, db_session, client_admin_real_uow, make_user):
    from app.modules.identity.domain.enums import UserRole
    from app.modules.identity.infrastructure.models import CompanyORM
    from app.modules.sync.application.work_price_approval_dto import IssueWorkPriceApproval
    from app.shared.domain.errors import NotFound
    from app.shared.infrastructure.db.uow_sqlalchemy import SqlAlchemyUnitOfWork
    _, _, proposal, url, body = prepare(case, db_session, client_admin_real_uow)
    issued = client_admin_real_uow.post(url, json=body).json()
    other = CompanyORM(name="Other work approval tenant")
    db_session.add(other)
    db_session.commit()
    actor = make_user(role=UserRole.ADMIN, company=other.id)
    try:
        for operation in ("history", "issue", "revoke"):
            with pytest.raises(NotFound), SqlAlchemyUnitOfWork() as uow:
                kwargs = {"company_id": other.id, "proposal_id": UUID(proposal["id"]), "actor_user_id": actor.id}
                if operation == "issue": kwargs["body"] = IssueWorkPriceApproval(**body)
                if operation == "revoke": kwargs.update(approval_id=UUID(issued["id"]), reason="Foreign revoke")
                getattr(service.WorkPriceApprovalService, operation)(uow, **kwargs)
    finally:
        db_session.rollback()
        db_session.query(AdminProfileORM).filter_by(user_id=actor.id).delete()
        db_session.delete(actor)
        db_session.flush()
        db_session.delete(other)
        db_session.commit()
