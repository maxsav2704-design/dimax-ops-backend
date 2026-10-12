from datetime import timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.earnings.infrastructure.models import CompletedWorkORM
from app.modules.sync.infrastructure.models import SyncEventORM, SyncQueueItemORM, SyncPriceResolutionORM
from app.shared.infrastructure.db.base import utcnow
from test_factory_earnings import activate, assert_applied, case, earning, submit
from test_price_conflict_resolution import clean_test_decisions


def retained(db, case, channel):
    db.expire_all()
    model = SyncEventORM if channel == "sync" else SyncQueueItemORM
    row = db.query(model).filter_by(company_id=case.company).one()
    code = row.apply_error if channel == "sync" else row.conflict_code
    assert code == "CONFLICT_FACTORY_PRICE"
    assert db.query(CompletedWorkORM).filter_by(company_id=case.company).count() == 0
    assert db.get(DoorORM, case.door).status == DoorStatus.IN_PROGRESS
    source = "sync_event" if channel == "sync" else "sync_queue"
    return row, f"/api/v1/admin/sync/price-conflicts/{source}/{row.id}"


@pytest.mark.parametrize("kind", ["DOOR", "ADDON"])
@pytest.mark.parametrize("channel", ["sync", "batch"])
@pytest.mark.parametrize("legacy", [False, True])
def test_explicit_evidence_resolves_old_price_once(case, db_session, client_admin_real_uow, kind, channel, legacy):
    before_activation = utcnow()
    v1, a1 = activate(case)
    at = before_activation if legacy else a1.effective_from
    activate(case, expected=1, previous=v1.id, door_price="300", addon_price="12")
    payload = {"base_version": 0} if kind == "DOOR" else {}
    if not legacy:
        payload["price_list_id"] = str(v1.id)
    event_id = str(uuid4())
    submit(case, kind, channel, at, event_id, payload)
    row, url = retained(db_session, case, channel)
    original = (row.payload.copy(), row.client_happened_at, row.created_at)
    review = client_admin_real_uow.get(url).json()
    assert review["analysis_code"] == ("LEGACY_EXECUTION_REVIEW" if legacy else "HISTORICAL_PRICE_REVIEW")
    assert review["resolution_available"] and review["requires_execution_evidence"]
    decision = {"request_id": str(uuid4()), "review_token": review["review_token"],
                "reason": "Verified assignment and execution against the site work record"}
    assert client_admin_real_uow.post(url + "/resolve", json=decision).status_code == 409
    retained(db_session, case, channel)
    decision["confirm_execution_evidence"] = True
    first = client_admin_real_uow.post(url + "/resolve", json=decision)
    assert first.status_code == 200, first.text
    repeat = client_admin_real_uow.post(url + "/resolve", json=decision)
    assert repeat.status_code == 200 and repeat.json() == first.json()
    replay = submit(case, kind, channel, at, event_id, payload)
    assert replay.status_code == 200, replay.text
    work, proof = earning(db_session, case)
    assert proof.price_list_id == v1.id
    assert work.amount_snapshot == (Decimal("250") if kind == "DOOR" else Decimal("13.50"))
    assert work.completed_at == at
    assert (row.payload, row.client_happened_at, row.created_at) == original
    resolution = db_session.query(SyncPriceResolutionORM).filter_by(company_id=case.company).one()
    assert resolution.quote_snapshot["execution_evidence_confirmed"] is True


@pytest.mark.parametrize("kind", ["DOOR", "ADDON"])
@pytest.mark.parametrize("channel", ["sync", "batch"])
@pytest.mark.parametrize("clock", ["naive", "future", "before_creation", "missing"])
def test_invalid_clock_is_retained_without_automatic_or_one_click_earnings(
        case, db_session, client_admin_real_uow, kind, channel, clock):
    _, activation = activate(case)
    at = {"naive": activation.effective_from.replace(tzinfo=None),
          "future": utcnow() + timedelta(days=1), "before_creation": utcnow() - timedelta(days=1),
          "missing": None}[clock]
    event_id = str(uuid4())
    for _ in range(2):
        submit(case, kind, channel, at, event_id)
    row, url = retained(db_session, case, channel)
    review = client_admin_real_uow.get(url).json()
    assert review["analysis_code"] == ("MISSING_EXECUTION_TIME" if clock == "missing" else "INVALID_EXECUTION_TIME")
    assert review["resolution_available"] is False and review["preview_amount"] is None
    assert row.client_time_has_timezone is (clock not in ("naive", "missing"))


@pytest.mark.parametrize("kind", ["DOOR", "ADDON"])
@pytest.mark.parametrize("channel", ["sync", "batch"])
def test_reassignment_cycle_does_not_prove_old_entitlement(case, db_session, client_admin_real_uow, kind, channel):
    _, activation = activate(case)
    door = db_session.get(DoorORM, case.door)
    old_boundary = door.assignment_started_at
    door.installer_id = None
    db_session.commit()
    db_session.refresh(door)
    assert door.assignment_started_at is None
    door.installer_id = case.installer
    db_session.commit()
    db_session.refresh(door)
    assert door.assignment_started_at > old_boundary
    payload = {"base_version": 0} if kind == "DOOR" else {}
    submit(case, kind, channel, activation.effective_from, extra_payload=payload)
    _, url = retained(db_session, case, channel)
    review = client_admin_real_uow.get(url).json()
    assert review["analysis_code"] == "ASSIGNMENT_EVIDENCE_REQUIRED"
    assert review["requires_execution_evidence"] is True


def test_assignment_boundary_is_server_owned(case, db_session):
    door = db_session.get(DoorORM, case.door)
    original = door.assignment_started_at
    db_session.execute(text("UPDATE doors SET assignment_started_at = :at WHERE id = :id"),
                       {"at": utcnow() - timedelta(days=30), "id": door.id})
    db_session.commit()
    db_session.refresh(door)
    assert door.assignment_started_at == original


@pytest.mark.parametrize("kind", ["DOOR", "ADDON"])
def test_server_receipt_proves_legacy_queue_without_trusting_device_version(case, db_session, installer_user, kind):
    at, event_id = utcnow(), uuid4()
    payload = ({"door_id": str(case.door), "status": "INSTALLED"} if kind == "DOOR" else
               {"addon_type_id": str(case.addon), "qty_done": "1.50", "comment": "QA"})
    row = SyncQueueItemORM(id=event_id, company_id=case.company, user_id=installer_user.id,
        project_id=case.project, entity_type="door" if kind == "DOOR" else "addon_fact",
        entity_id=case.door if kind == "DOOR" else event_id,
        operation_type="DOOR_SET_STATUS" if kind == "DOOR" else "ADDON_FACT_CREATE",
        payload=payload, base_version=0, client_happened_at=at, client_time_has_timezone=True,
        created_at=utcnow(), status="PENDING")
    db_session.add(row)
    db_session.commit()
    received = row.created_at
    v1, _ = activate(case)
    activate(case, expected=1, previous=v1.id, door_price="300", addon_price="12")
    assert_applied(submit(case, kind, "batch", at, str(event_id)), "batch")
    work, proof = earning(db_session, case)
    assert work.amount_snapshot == (Decimal("250") if kind == "DOOR" else Decimal("13.50"))
    assert proof.price_list_id == v1.id and proof.selection == "FIRST_CONFIRMED_LEGACY"
    assert db_session.get(SyncQueueItemORM, UUID(str(event_id))).created_at == received


def test_direct_addon_cannot_bypass_old_price_review(case, db_session):
    v1, a1 = activate(case)
    activate(case, expected=1, previous=v1.id)
    response = submit(case, "ADDON", "direct", a1.effective_from)
    assert response.status_code == 409, response.text
    assert db_session.query(CompletedWorkORM).filter_by(company_id=case.company).count() == 0


@pytest.mark.parametrize("channel", ["sync", "batch"])
def test_installer_cannot_supply_review_authority(case, db_session, channel):
    _, a1 = activate(case)
    response = submit(case, "DOOR", channel, a1.effective_from,
                      extra_payload={"reviewed_execution": True, "confirm_execution_evidence": True})
    assert response.status_code == 200, response.text
    assert db_session.query(CompletedWorkORM).filter_by(company_id=case.company).count() == 0
