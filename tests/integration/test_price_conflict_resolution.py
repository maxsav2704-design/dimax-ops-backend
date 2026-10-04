from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.modules.audit.application.service import AuditService
from app.modules.audit.infrastructure.models import AuditLogORM
from app.modules.addons.infrastructure.models import AddonTypeORM
from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.earnings.infrastructure.models import CompletedWorkORM
from app.modules.identity.infrastructure.models import AdminProfileORM
from app.modules.sync.application.price_resolution_service import PriceConflictResolutionService
from app.modules.sync.application.price_review_dto import ResolvePriceConflict
from app.modules.sync.infrastructure.models import SyncPriceResolutionORM
from app.modules.sync.infrastructure.models import SyncEventORM
from app.shared.domain.errors import Conflict
from app.shared.infrastructure.db.uow_sqlalchemy import SqlAlchemyUnitOfWork
from test_factory_earnings import activate, assert_applied, case, earning, submit
from test_factory_price_review import conflict


@pytest.fixture(autouse=True)
def clean_test_decisions(db_session, company_id):
    yield
    db_session.rollback()
    # This privileged cleanup is limited to this test's tenant and the explicit test database.
    if db_session.query(SyncPriceResolutionORM).filter_by(company_id=company_id).first() is not None:
        assert db_session.execute(text("SELECT current_database()")).scalar_one().endswith("_tests")
        db_session.execute(text("ALTER TABLE sync_price_resolutions DISABLE TRIGGER sync_price_resolution_immutable"))
        db_session.execute(text("DELETE FROM sync_price_resolutions WHERE company_id=:cid"), {"cid": company_id})
        db_session.execute(text("ALTER TABLE sync_price_resolutions ENABLE TRIGGER sync_price_resolution_immutable"))
        db_session.commit()


def decision(client, url):
    review = client.get(url)
    assert review.status_code == 200, review.text
    assert review.json()["resolution_available"] is True, review.text
    return {"request_id": str(uuid4()), "review_token": review.json()["review_token"],
            "reason": "Execution checked against confirmed factory terms"}


@pytest.mark.parametrize("kind,channel", [("DOOR", "batch"), ("ADDON", "batch"), ("ADDON", "sync"), ("DOOR", "sync")])
def test_resolves_once_preserves_original_and_acknowledges_mobile(case, db_session, client_admin_real_uow, kind, channel):
    row, url, v1, v2 = conflict(case, db_session, kind, channel)
    if kind == "DOOR" and channel == "sync":
        row.payload = {**row.payload, "base_version": 0}
        db_session.commit()
    original = row.payload.copy()
    at = row.client_happened_at
    body = decision(client_admin_real_uow, url)
    # Later amendments must not affect a previously reviewed execution price.
    activate(case, expected=2, previous=v2.id, door_price="400", addon_price="20")
    first = client_admin_real_uow.post(url + "/resolve", json=body)
    assert first.status_code == 200, first.text
    assert client_admin_real_uow.post(url + "/resolve", json=body).json() == first.json()
    assert client_admin_real_uow.post(url + "/resolve", json={**body, "request_id": str(uuid4())}).status_code == 409
    assert client_admin_real_uow.post(url + "/resolve", json={**body, "reason": "Different decision reason"}).status_code == 409
    work, proof = earning(db_session, case)
    assert work.amount_snapshot == Decimal("300" if kind == "DOOR" else "18")
    assert proof.price_list_id == v2.id and proof.performed_at == at
    db_session.refresh(row)
    assert row.payload == original and row.client_happened_at == at
    event_id = row.client_event_id if channel == "sync" else str(row.id)
    assert_applied(submit(case, kind, channel, at, event_id, original), channel)
    assert db_session.query(CompletedWorkORM).filter_by(company_id=case.company).count() == 1
    resolution = db_session.query(SyncPriceResolutionORM).filter_by(company_id=case.company).one()
    assert resolution.original_command["payload"] == original
    assert resolution.completed_work_id == work.id and resolution.actor_user_id == case.actor
    assert db_session.query(AuditLogORM).filter_by(company_id=case.company, action="SYNC_FACTORY_PRICE_RESOLVED").count() == 1
    assert client_admin_real_uow.get("/api/v1/admin/sync/problems?status=price_conflict").json()["total"] == 0
    if channel == "sync":
        response = case.client.post("/api/v1/installer/sync", json={"events": [],
            "price_resolution_checks": [event_id, event_id, "unrelated-event"]})
        assert response.status_code == 200, response.text
        assert response.json()["acks"] == [{"client_event_id": event_id, "ok": True, "applied": False, "error": None}]
    with pytest.raises(DBAPIError):
        db_session.execute(text("UPDATE sync_price_resolutions SET reason='tampered decision' WHERE id=:id"), {"id": resolution.id})
    db_session.rollback()


@pytest.mark.parametrize("change", ["assignment", "version", "locked", "quantity", "permission", "stale_token"])
def test_changed_conditions_do_not_apply_or_earn(case, db_session, client_admin_real_uow, change):
    kind = "ADDON" if change == "quantity" else "DOOR"
    row, url, _, _ = conflict(case, db_session, kind)
    body = decision(client_admin_real_uow, url)
    door = db_session.get(DoorORM, case.door)
    if change == "assignment":
        door.installer_id = None
    elif change == "version":
        door.version += 1
    elif change == "locked":
        door.is_locked = True
    elif change == "quantity":
        row.payload = {**row.payload, "qty_done": "2"}
    elif change == "permission":
        db_session.query(AdminProfileORM).filter_by(user_id=case.actor).one().can_view_rates = False
    else:
        body["review_token"] = "0" * 64
    db_session.commit()
    response = client_admin_real_uow.post(url + "/resolve", json=body)
    assert response.status_code == (403 if change == "permission" else 409), response.text
    assert db_session.query(CompletedWorkORM).filter_by(company_id=case.company).count() == 0
    assert db_session.query(SyncPriceResolutionORM).filter_by(company_id=case.company).count() == 0
    db_session.refresh(row)
    assert row.conflict_code == "CONFLICT_FACTORY_PRICE"


def test_failed_audit_rolls_back_work_and_decision(case, db_session, client_admin_real_uow, monkeypatch):
    row, url, _, _ = conflict(case, db_session)
    body = ResolvePriceConflict(**decision(client_admin_real_uow, url))
    original_add = AuditService.add
    def fail_audit(*args, **kwargs):
        if kwargs["action"] == "SYNC_FACTORY_PRICE_RESOLVED":
            raise RuntimeError("Audit unavailable")
        return original_add(*args, **kwargs)
    monkeypatch.setattr(AuditService, "add", fail_audit)
    with pytest.raises(RuntimeError, match="Audit unavailable"), SqlAlchemyUnitOfWork() as uow:
        PriceConflictResolutionService.resolve(uow, company_id=case.company, actor_user_id=case.actor,
            source="sync_queue", item_id=row.id, body=body)
    db_session.expire_all()
    assert db_session.get(DoorORM, case.door).status == DoorStatus.IN_PROGRESS
    assert db_session.query(CompletedWorkORM).filter_by(company_id=case.company).count() == 0
    assert db_session.query(SyncPriceResolutionORM).filter_by(company_id=case.company).count() == 0
    assert row.conflict_code == "CONFLICT_FACTORY_PRICE"


def test_concurrent_decisions_create_one_earning(case, db_session, client_admin_real_uow):
    row, url, _, _ = conflict(case, db_session, "ADDON")
    body = ResolvePriceConflict(**decision(client_admin_real_uow, url))
    gate = Barrier(2)
    company, actor, item = case.company, case.actor, row.id
    def resolve():
        gate.wait(timeout=15)
        with SqlAlchemyUnitOfWork() as uow:
            return PriceConflictResolutionService.resolve(uow, company_id=company, actor_user_id=actor,
                source="sync_queue", item_id=item, body=body)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.submit(resolve), pool.submit(resolve)
        assert a.result(timeout=60) == b.result(timeout=60)
    assert db_session.query(CompletedWorkORM).filter_by(company_id=case.company).count() == 1


def test_installer_and_untrusted_fields_cannot_resolve(case, db_session, client_admin_real_uow):
    _, url, _, _ = conflict(case, db_session)
    body = decision(client_admin_real_uow, url)
    assert case.client.post(url + "/resolve", json=body).status_code == 403
    for extra in ({"amount": "1"}, {"price_list_id": str(uuid4())}, {"rate": "1"}):
        assert client_admin_real_uow.post(url + "/resolve", json={**body, **extra}).status_code == 422
    assert client_admin_real_uow.post(url + "/resolve", json={**body, "reason": "   "}).status_code == 422


def test_no_version_evidence_is_not_silently_repaired(case, db_session, client_admin_real_uow):
    row, url, _, _ = conflict(case, db_session, channel="sync")
    assert client_admin_real_uow.get(url).json()["resolution_available"] is False
    response = client_admin_real_uow.post(url + "/resolve", json={"request_id": str(uuid4()),
        "review_token": "0" * 64, "reason": "Missing door version cannot be invented"})
    assert response.status_code == 409, response.text
    assert db_session.query(CompletedWorkORM).filter_by(company_id=case.company).count() == 0


def test_status_check_never_executes_unresolved_or_missing_work(case, db_session):
    row, _, _, _ = conflict(case, db_session, "ADDON", "sync")
    response = case.client.post("/api/v1/installer/sync", json={"events": [],
        "price_resolution_checks": [row.client_event_id, "unknown-price-event"]})
    assert response.status_code == 200, response.text
    assert response.json()["acks"] == []
    assert db_session.query(CompletedWorkORM).filter_by(company_id=case.company).count() == 0
    db_session.refresh(row)
    assert row.apply_error == "CONFLICT_FACTORY_PRICE"


def test_price_ack_is_scoped_to_installer_and_company(case, db_session, client_admin_real_uow, make_installer):
    row, url, _, _ = conflict(case, db_session, "ADDON", "sync")
    body = decision(client_admin_real_uow, url)
    assert client_admin_real_uow.post(url + "/resolve", json=body).status_code == 200
    other = make_installer()
    with SqlAlchemyUnitOfWork() as uow:
        assert uow.sync_events.resolved_price_events(company_id=case.company, installer_id=other.id,
            client_event_ids=[row.client_event_id]) == []
        assert uow.sync_events.resolved_price_events(company_id=uuid4(), installer_id=case.installer,
            client_event_ids=[row.client_event_id]) == []


def test_changed_unit_between_confirmed_versions_needs_separate_review(case, db_session, client_admin_real_uow):
    v1, _ = activate(case)
    db_session.get(AddonTypeORM, case.addon).unit = "m"
    db_session.commit()
    _, activation = activate(case, expected=1, previous=v1.id, addon_price="12")
    response = submit(case, "ADDON", "sync", activation.effective_from, extra_payload={"price_list_id": str(v1.id)})
    assert response.status_code == 200, response.text
    row = db_session.query(SyncEventORM).filter_by(company_id=case.company).one()
    url = f"/api/v1/admin/sync/price-conflicts/sync_event/{row.id}"
    review = client_admin_real_uow.get(url).json()
    assert review["analysis_code"] == "ORIGINAL_PRICE_UNAVAILABLE"
    assert review["resolution_available"] is False
    response = client_admin_real_uow.post(url + "/resolve", json={"request_id": str(uuid4()),
        "review_token": "0" * 64, "reason": "Must not convert pieces to metres"})
    assert response.status_code == 409, response.text
    assert db_session.query(CompletedWorkORM).filter_by(company_id=case.company).count() == 0


@pytest.mark.parametrize("scope,rates,expected", [("OPERATIONS", True, 200), ("OPERATIONS", False, 403),
    ("FINANCE", True, 403), ("VIEWER", True, 403), ("INSTALLER", False, 403)])
def test_live_jwt_resolution_permissions(case, db_session, client_admin_real_uow, client_raw, make_user, scope, rates, expected):
    from app.modules.identity.domain.enums import UserRole
    _, url, _, _ = conflict(case, db_session)
    body = decision(client_admin_real_uow, url)
    user = make_user(role=UserRole.INSTALLER if scope == "INSTALLER" else UserRole.ADMIN)
    if scope != "INSTALLER":
        profile = db_session.query(AdminProfileORM).filter_by(user_id=user.id).one()
        profile.admin_scope, profile.can_view_rates = scope, rates
        db_session.commit()
    assert client_raw.post(url + "/resolve", json=body).status_code == 401
    login = client_raw.post("/api/v1/auth/login", json={"company_id": str(case.company),
        "email": user.email, "password": "secret123", "device_id": "price-decision-test"})
    assert login.status_code == 200, login.text
    response = client_raw.post(url + "/resolve", json=body,
        headers={"Authorization": f'Bearer {login.json()["access_token"]}'})
    assert response.status_code == expected, response.text
