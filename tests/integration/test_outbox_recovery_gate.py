"""Opt-in tests. Never run against a working database."""
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.modules.audit.infrastructure.models import AuditLogORM
from app.modules.identity.infrastructure.models import AdminProfileORM, UserORM
from app.modules.outbox.domain.enums import OutboxChannel, OutboxStatus
from app.modules.outbox.infrastructure.models import OutboxMessageORM as Message
from app.modules.outbox.infrastructure.recovery_gate import lock_delivery
from app.modules.outbox.infrastructure.recovery_models import OutboxRecoveryItemORM as Item
from app.modules.outbox.infrastructure.repositories import OutboxRepository

pytestmark = pytest.mark.skipif(os.getenv("DIMAX_RECOVERY_GATE_TEST") != "synthetic-only",
                                reason="Requires isolated recovery gate acceptance")
PREFIX = "/api/v1/admin/outbox/recovery"


@pytest.fixture(autouse=True)
def guard():
    for value in (settings.DATABASE_URL, os.environ["TEST_DATABASE_URL"]):
        url = make_url(value)
        assert url.host == "127.0.0.1" and url.database == "dimax_gate_tests"
    assert os.environ["APP_ENV"] == "test"


@pytest.fixture
def case(client, db_session, company_id, admin_user, monkeypatch):
    monkeypatch.setattr(settings, "OUTBOX_RECOVERY_EPOCH", uuid4())
    now = datetime.now(timezone.utc)
    messages = [Message(company_id=company_id, channel=OutboxChannel.EMAIL,
                        status=status, scheduled_at=now + delta, attempts=attempts, max_attempts=5,
                        payload={"to_email": "test@dimax.example", "subject": label, "body_text": "Synthetic"})
                for label, status, attempts, delta in (
                    ("due", OutboxStatus.PENDING, 0, timedelta(minutes=-1)),
                    ("exhausted", OutboxStatus.FAILED, 5, timedelta(minutes=-1)),
                    ("future", OutboxStatus.PENDING, 0, timedelta(days=30)),
                    ("sent", OutboxStatus.SENT, 1, timedelta(days=-1)),
                )]
    db_session.add_all(messages)
    db_session.commit()
    result = SimpleNamespace(client=client, session=db_session, company=company_id,
                             user=admin_user, ids=[message.id for message in messages])
    yield result
    db_session.rollback()
    # Only this synthetic company; normal teardown follows, never production.
    db_session.execute(text("SET LOCAL session_replication_role = 'replica'"))
    for table in ("outbox_recovery_decisions", "outbox_recovery_items", "outbox_recoveries"):
        db_session.execute(text(f"DELETE FROM {table} WHERE company_id = :cid"), {"cid": company_id})
    db_session.commit()


def begin(case):
    response = case.client.post(PREFIX + "/begin", json={"reason": "Synthetic restore"})
    assert response.status_code == 200, response.text
    response = case.client.get(PREFIX + "/items")
    assert response.status_code == 200, response.text
    return response.json()


def decide(case, item, action="HOLD", **changes):
    body = {"request_id": str(uuid4()), "expected_revision": item["revision"], "action": action,
            "reason": "Reviewed synthetic provider evidence", "evidence": "Synthetic evidence reference 123"}
    if action == "ACCEPTED":
        body["accepted_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    body.update(changes)
    return case.client.post(PREFIX + f"/items/{item['id']}/decisions", json=body), body


def ready(case):
    with Session(case.session.get_bind()) as session:
        return [row.id for row in OutboxRepository(session).lock_next_batch(company_id=case.company)]


def test_gate_blocks_before_review_and_release_requires_decisions(case):
    assert ready(case) == []
    items = begin(case)
    assert len(items) == 3 and str(case.ids[3]) not in {item["outbox_id"] for item in items}
    assert case.client.post(PREFIX + "/release", json={"reason": "Premature"}).status_code == 409
    assert case.client.post(f"/api/v1/admin/outbox/{case.ids[0]}/retry", json={"reason": "Bypass"}).status_code == 409
    assert ready(case) == []
    for item in items:
        assert decide(case, item)[0].status_code == 200
    response = case.client.post(PREFIX + "/release", json={"reason": "Uncertain mail stays held"})
    assert response.status_code == 200 and response.json()["held"] == 3
    assert ready(case) == []
    assert case.client.post(f"/api/v1/admin/outbox/{case.ids[0]}/retry", json={"reason": "Bypass"}).status_code == 409


def test_hold_then_retry_accepted_and_future_preserved(case):
    items = begin(case)
    for item in items:
        assert decide(case, item)[0].status_code == 200
    assert case.client.post(PREFIX + "/release", json={"reason": "Keep holds"}).status_code == 200
    for item in items:
        item["revision"] = 1
        action = "ACCEPTED" if item["outbox_id"] == str(case.ids[0]) else "RETRY"
        assert decide(case, item, action)[0].status_code == 200
    assert ready(case) == [case.ids[1]]
    case.session.expire_all()
    assert case.session.get(Message, case.ids[0]).status == OutboxStatus.SENT
    assert case.session.get(Message, case.ids[1]).max_attempts == 6
    assert case.session.get(Message, case.ids[2]).scheduled_at > datetime.now(timezone.utc)
    decisions = case.client.get(PREFIX + "/decisions").json()
    assert len(decisions) == 6
    assert len(case.client.get(PREFIX + "/decisions?limit=2&offset=2").json()) == 2
    assert all(row["actor_id"] == str(case.user.id) for row in decisions)
    assert case.session.scalar(select(AuditLogORM.id).where(AuditLogORM.action == "OUTBOX_RECOVERY_RELEASE"))


def test_epoch_rotation_and_configuration_removal_fail_closed(case, monkeypatch):
    for item in begin(case):
        assert decide(case, item, "RETRY")[0].status_code == 200
    assert case.client.post(PREFIX + "/release", json={"reason": "Evidence checked"}).status_code == 200
    assert len(ready(case)) == 2
    old = settings.OUTBOX_RECOVERY_EPOCH
    monkeypatch.setattr(settings, "OUTBOX_RECOVERY_EPOCH", uuid4())
    assert ready(case) == []
    assert case.client.get(PREFIX).json()["state"] == "REVIEW_REQUIRED"
    begin(case)
    monkeypatch.setattr(settings, "OUTBOX_RECOVERY_EPOCH", old)
    assert ready(case) == []  # A worker with stale configuration cannot bypass a newer review.
    monkeypatch.setattr(settings, "OUTBOX_RECOVERY_EPOCH", None)
    assert ready(case) == []
    assert case.client.get(PREFIX).json()["state"] == "CONFIGURATION_REQUIRED"


def test_decision_is_idempotent_and_history_is_immutable(case):
    item = begin(case)[0]
    response, body = decide(case, item)
    assert response.status_code == 200
    url = PREFIX + f"/items/{item['id']}/decisions"
    replay = case.client.post(url, json=body)
    assert replay.status_code == 200 and replay.json() == response.json()
    assert case.client.post(url, json=dict(body, reason="Changed")).status_code == 409
    assert decide(case, item)[0].status_code == 409
    for sql in ("UPDATE outbox_recovery_decisions SET reason='changed' WHERE company_id=:cid",
                "DELETE FROM outbox_recovery_decisions WHERE company_id=:cid"):
        with pytest.raises(DBAPIError), case.session.begin_nested():
            case.session.execute(text(sql), {"cid": case.company})
    assert len(case.client.get(PREFIX + "/decisions").json()) == 1


@pytest.mark.parametrize("changes,expected", [
    ({"reason": "   "}, 422), ({"evidence": ""}, 422),
    ({"action": "ACCEPTED", "accepted_at": None}, 422),
    ({"accepted_at": "2026-01-01T00:00:00"}, 422),
    ({"action": "ACCEPTED", "accepted_at": "2999-01-01T00:00:00Z"}, 422),
    ({"action": "DROP"}, 422),
])
def test_invalid_decisions_are_rejected(case, changes, expected):
    response, _ = decide(case, begin(case)[0], **changes)
    assert response.status_code == expected, response.text


def test_changed_payload_and_foreign_item_are_rejected(case):
    item = begin(case)[0]
    row = case.session.get(Message, item["outbox_id"])
    row.payload = dict(row.payload, subject="Changed after snapshot")
    case.session.commit()
    assert decide(case, item, "RETRY")[0].status_code == 409
    item["id"] = str(uuid4())
    assert decide(case, item)[0].status_code == 404


@pytest.mark.parametrize("scope", ["OPERATIONS", "FINANCE", "VIEWER"])
def test_only_owner_can_open_and_release(case, scope):
    items = begin(case)
    profile = case.session.scalar(select(AdminProfileORM).where(AdminProfileORM.user_id == case.user.id))
    profile.admin_scope = scope
    case.session.commit()
    assert case.client.post(PREFIX + "/begin", json={"reason": "Not owner"}).status_code == 403
    assert case.client.post(PREFIX + "/release", json={"reason": "Not owner"}).status_code == 403
    assert decide(case, items[0])[0].status_code == (200 if scope == "OPERATIONS" else 403)


def test_dispatch_and_admin_share_transaction_lock(case):
    with Session(case.session.get_bind()) as other:
        assert lock_delivery(case.session, wait=False)
        assert not lock_delivery(other, wait=False)
        assert OutboxRepository(other).lock_next_batch(company_id=case.company) == []
        case.session.rollback()
        assert lock_delivery(other, wait=False)


def test_installer_cannot_review_even_with_forged_admin_dependency(case):
    items = begin(case)
    user = case.session.get(UserORM, case.user.id)
    user.role = "INSTALLER"
    case.session.commit()
    assert case.client.get(PREFIX).status_code == 403
    assert decide(case, items[0])[0].status_code == 403


def test_database_rejects_cross_tenant_recovery_item(case):
    item = begin(case)[0]
    with pytest.raises(DBAPIError), case.session.begin_nested():
        case.session.execute(text("UPDATE outbox_recovery_items SET company_id=:foreign WHERE id=:id"),
                             {"foreign": uuid4(), "id": item["id"]})
    assert case.session.get(Item, item["id"]).company_id == case.company


def test_plain_deployment_unchanged_until_recovery_activated(case, monkeypatch):
    monkeypatch.setattr(settings, "OUTBOX_RECOVERY_EPOCH", None)
    assert ready(case) == [case.ids[0]]
    assert case.client.get(PREFIX).json()["state"] == "NOT_ACTIVATED"
    assert case.client.post(PREFIX + "/begin", json={"reason": "Missing configuration"}).status_code == 409
