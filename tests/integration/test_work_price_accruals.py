import runpy
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.modules.addons.infrastructure.models import AddonTypeORM, ProjectAddonFactORM
from app.modules.audit.application.service import AuditService
from app.modules.audit.infrastructure.models import AuditLogORM
from app.modules.doors.application.commands import AdminOverrideDoor
from app.modules.doors.application.use_cases import DoorUseCases
from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.earnings.infrastructure.models import CompletedWorkORM
from app.modules.earnings.infrastructure.work_price_models import WorkPriceAccrualORM
from app.modules.identity.infrastructure.models import AdminProfileORM
from app.modules.sync.application.work_price_accrual_dto import AccrueWorkPrice
from app.modules.sync.application.work_price_accrual_service import WorkPriceAccrualService
from app.modules.sync.application import work_price_accrual_service as service
from app.shared.infrastructure.db.base import utcnow
from app.shared.infrastructure.db.uow_sqlalchemy import SqlAlchemyUnitOfWork
from test_factory_earnings import submit, assert_applied
from test_factory_approval_email import isolated_email
from test_work_price_proposals import case, clean_test_proposals, proposal_body
from test_work_price_approvals import clean_invitations, prepare, send, confirmation, PUBLIC


@pytest.fixture(autouse=True)
def clean_accruals(db_session, company_id, clean_invitations):
    yield
    db_session.rollback()
    assert db_session.execute(text("SELECT current_database()")).scalar_one().endswith("_tests")
    db_session.execute(text("ALTER TABLE work_price_accruals DISABLE TRIGGER work_price_accrual_guard"))
    db_session.execute(text("DELETE FROM work_price_accruals WHERE company_id=:cid"), {"cid": company_id})
    db_session.execute(text("ALTER TABLE work_price_accruals ENABLE TRIGGER work_price_accrual_guard"))
    db_session.commit()


def ready(case, db, client, kind="ADDON", channel="batch", legacy=False):
    row, proposals, proposal, invitations, invite_body = prepare(case, db, client, kind, channel, legacy)
    issued, token = send(client, invitations, invite_body)
    response = client.post(PUBLIC + "/confirm", json=confirmation(client, token))
    assert response.status_code == 200, response.text
    url = f'/api/v1/admin/sync/work-price-approvals/{issued["id"]}/accrual'
    preview = client.get(url)
    assert preview.status_code == 200, preview.text
    assert preview.headers["cache-control"] == "no-store"
    assert preview.json()["accrual"] is None
    body = {"request_id": str(uuid4()), "approval_hash": preview.json()["approval_hash"],
            "reason": "Execution and independent factory decision checked", "confirm_accrual": True}
    return row, proposals, url, body


@pytest.mark.parametrize("kind", ["DOOR", "ADDON"])
@pytest.mark.parametrize("channel", ["sync", "batch"])
@pytest.mark.parametrize("legacy", [False, True])
def test_accrue_once_and_ack_original_mobile_command(case, db_session, client_admin_real_uow, kind, channel, legacy):
    client = client_admin_real_uow
    row, _, url, body = ready(case, db_session, client, kind, channel, legacy)
    original_payload, original_time = dict(row.payload), row.client_happened_at
    event_id = row.client_event_id if channel == "sync" else str(row.id)
    check = {"events": [], "price_resolution_checks": [event_id, event_id, "unrelated-event"]}
    if channel == "sync":
        assert case.client.post("/api/v1/installer/sync", json=check).json()["acks"] == []
    result = client.post(url, json=body)
    assert result.status_code == 200, result.text
    assert client.post(url, json=body).json() == result.json()
    assert client.post(url, json={**body, "request_id": str(uuid4())}).status_code == 409
    assert client.post(url, json={**body, "reason": "Different administrator decision"}).status_code == 409
    assert client.get(url).json()["accrual"] == result.json()
    db_session.expire_all()
    assert row.payload == original_payload and row.client_happened_at == original_time
    if channel == "sync":
        checked = case.client.post("/api/v1/installer/sync", json=check)
        assert checked.status_code == 200, checked.text
        assert checked.json()["acks"] == [{"client_event_id": event_id, "ok": True, "applied": False, "error": None}]
        with SqlAlchemyUnitOfWork() as uow:
            assert uow.sync_events.resolved_price_events(company_id=case.company, installer_id=uuid4(), client_event_ids=[event_id]) == []
            assert uow.sync_events.resolved_price_events(company_id=uuid4(), installer_id=case.installer, client_event_ids=[event_id]) == []
    assert_applied(submit(case, kind, channel, original_time, event_id,
                          extra_payload={"base_version": 0} if kind == "DOOR" else {}), channel)
    db_session.expire_all()
    work = db_session.query(CompletedWorkORM).filter_by(company_id=case.company).one()
    assert work.id == UUID(result.json()["completed_work_id"])
    assert work.rate_snapshot == Decimal("9.01")
    assert work.amount_snapshot == Decimal("9.01" if kind == "DOOR" else "13.52")
    assert work.completed_at == original_time
    assert work.installer_id == case.installer and work.project_id == case.project
    mobile = case.client.get("/api/v1/installer/earnings/summary", params={
        "period": "day", "date": original_time.astimezone(ZoneInfo("Asia/Jerusalem")).date().isoformat()})
    assert mobile.status_code == 200, mobile.text
    assert Decimal(mobile.json()["total"]) == work.amount_snapshot
    assert mobile.json()["rows"][0]["id"] == str(work.id)
    ledger = client.get("/api/v1/admin/earnings/ledger").json()["items"]
    assert len(ledger) == 1 and not ledger[0]["can_correct"]
    assert ledger[0]["factory_price"] is None and ledger[0]["work_price"]["id"] == result.json()["id"]
    assert db_session.query(AuditLogORM).filter_by(company_id=case.company, entity_type="WORK_PRICE_ACCRUAL").count() == 1
    for command in ("UPDATE work_price_accruals SET amount=1 WHERE id=:id", "DELETE FROM work_price_accruals WHERE id=:id"):
        with pytest.raises(DBAPIError):
            db_session.execute(text(command), {"id": UUID(result.json()["id"])})
        db_session.rollback()
    for command in ("UPDATE completed_work SET rate_snapshot=1, amount_snapshot=quantity WHERE id=:id",
                    "DELETE FROM completed_work WHERE id=:id"):
        with pytest.raises(DBAPIError):
            db_session.execute(text(command), {"id": work.id})
        db_session.rollback()


@pytest.mark.parametrize("change", ["assignment", "version", "locked", "quantity", "unit", "permission", "proposal", "payload", "time", "identity"])
def test_stale_work_cannot_accrue(case, db_session, client_admin_real_uow, change):
    client = client_admin_real_uow
    kind = "ADDON" if change in ("quantity", "unit") else "DOOR"
    row, proposals, url, body = ready(case, db_session, client, kind)
    door = db_session.get(DoorORM, case.door)
    if change == "assignment": door.installer_id = None
    elif change == "version": door.version += 1
    elif change == "locked": door.is_locked = True
    elif change == "identity": door.door_code = "Another work reference"
    elif change == "quantity": row.payload = {**row.payload, "qty_done": "2"}
    elif change == "unit": db_session.get(AddonTypeORM, case.addon).unit = "hours"
    elif change == "permission": db_session.query(AdminProfileORM).filter_by(user_id=case.actor).one().can_view_rates = False
    elif change == "payload": row.payload = {**row.payload, "rate": "1"}
    elif change == "time": row.client_happened_at = None
    else:
        assert client.post(proposals, json=proposal_body(client, proposals, rate="12.00")).status_code == 200
    db_session.commit()
    expected = 422 if change == "payload" else 403 if change in ("permission", "assignment") else 409
    assert client.post(url, json=body).status_code == expected
    assert db_session.query(CompletedWorkORM).filter_by(company_id=case.company).count() == 0
    assert db_session.query(WorkPriceAccrualORM).filter_by(company_id=case.company).count() == 0


@pytest.mark.parametrize("override", [{"confirm_accrual": False}, {"confirm_accrual": "true"},
    {"rate": "999"}, {"amount": "999"}, {"reason": "short"}, {"approval_hash": "a" * 64}])
def test_explicit_consent_and_no_caller_price(case, db_session, client_admin_real_uow, override):
    _, _, url, body = ready(case, db_session, client_admin_real_uow)
    assert client_admin_real_uow.post(url, json={**body, **override}).status_code in (409, 422)
    assert db_session.query(CompletedWorkORM).filter_by(company_id=case.company).count() == 0


def test_pending_confirmation_cannot_accrue(case, db_session, client_admin_real_uow):
    client = client_admin_real_uow
    _, _, _, invitations, body = prepare(case, db_session, client)
    issued, _ = send(client, invitations, body)
    url = f'/api/v1/admin/sync/work-price-approvals/{issued["id"]}/accrual'
    assert client.get(url).status_code == 409
    assert client.post(url, json={"request_id": str(uuid4()), "approval_hash": "a" * 64,
        "reason": "Attempt without factory confirmation", "confirm_accrual": True}).status_code == 409


def test_foreign_tenant_cannot_read_or_accrue(case, db_session, client_admin_real_uow):
    from app.api.v1.deps import CurrentUser, require_admin
    client = client_admin_real_uow
    _, _, url, body = ready(case, db_session, client)
    client.app.dependency_overrides[require_admin] = lambda: CurrentUser(id=case.actor, company_id=uuid4(), role="ADMIN")
    assert client.get(url).status_code in (403, 404)
    assert client.post(url, json=body).status_code in (403, 404)


@pytest.mark.parametrize("kind", ["DOOR", "ADDON"])
def test_failure_rolls_back_work_earning_ack_and_proof(case, db_session, client_admin_real_uow, monkeypatch, kind):
    row, _, url, body = ready(case, db_session, client_admin_real_uow, kind)
    old_status = getattr(row, "status", None)
    original_add = AuditService.add
    def fail(uow, **kwargs):
        if kwargs.get("entity_type") == "WORK_PRICE_ACCRUAL":
            raise RuntimeError("Audit unavailable")
        return original_add(uow, **kwargs)
    monkeypatch.setattr(AuditService, "add", fail)
    assert client_admin_real_uow.post(url, json=body).status_code == 500
    db_session.expire_all()
    assert row.status == old_status
    assert db_session.get(DoorORM, case.door).status == DoorStatus.IN_PROGRESS
    assert db_session.query(CompletedWorkORM).filter_by(company_id=case.company).count() == 0
    assert db_session.query(ProjectAddonFactORM).filter_by(company_id=case.company).count() == 0
    assert db_session.query(WorkPriceAccrualORM).filter_by(company_id=case.company).count() == 0


def test_concurrent_retries_serialize_one_accrual(case, db_session, client_admin_real_uow):
    _, _, url, values = ready(case, db_session, client_admin_real_uow)
    body = AccrueWorkPrice(**values)
    company, actor, approval = case.company, case.actor, UUID(url.split("/")[-2])
    gate = Barrier(2)
    def accrue():
        gate.wait(timeout=15)
        with SqlAlchemyUnitOfWork() as uow:
            return WorkPriceAccrualService.accrue(uow, company_id=company, actor_user_id=actor, approval_id=approval, body=body)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.submit(accrue), pool.submit(accrue)
        assert a.result(timeout=60) == b.result(timeout=60)
    assert db_session.query(CompletedWorkORM).filter_by(company_id=case.company).count() == 1


def test_valid_decision_survives_link_expiry_and_reversal_preserves_basis(case, db_session, client_admin_real_uow, make_reason, monkeypatch):
    client = client_admin_real_uow
    _, _, url, body = ready(case, db_session, client, "DOOR")
    now = utcnow()
    monkeypatch.setattr(service, "utcnow", lambda: now + timedelta(days=8))
    response = client.post(url, json=body)
    assert response.status_code == 200, response.text
    reason = make_reason()
    with SqlAlchemyUnitOfWork() as uow:
        DoorUseCases.admin_override(uow, AdminOverrideDoor(case.company, case.actor, case.door, "NOT_INSTALLED",
            reason_id=reason.id, override_reason="QA cancellation"), actor_role="ADMIN")
    ledger = client.get("/api/v1/admin/earnings/ledger").json()["items"]
    assert len(ledger) == 2
    assert sum(Decimal(item["amount_snapshot"]) for item in ledger) == 0
    assert all(item["work_price"]["id"] == response.json()["id"] for item in ledger)
    assert client.post(url, json=body).json() == response.json()
    assert client.post("/api/v1/admin/earnings/corrections", json={
        "completed_work_id": response.json()["completed_work_id"], "rate_snapshot": "500", "reason": "Manual override"}).status_code == 409


def test_nonempty_accrual_downgrade_is_blocked(case, db_session, client_admin_real_uow, monkeypatch):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    _, _, url, body = ready(case, db_session, client_admin_real_uow)
    assert client_admin_real_uow.post(url, json=body).status_code == 200
    downgrade = runpy.run_path("alembic/versions/0074_work_price_accruals.py")["downgrade"]
    monkeypatch.setitem(downgrade.__globals__, "op", Operations(MigrationContext.configure(db_session.connection())))
    with pytest.raises(RuntimeError, match="accrual history exists"):
        downgrade()
    db_session.rollback()
