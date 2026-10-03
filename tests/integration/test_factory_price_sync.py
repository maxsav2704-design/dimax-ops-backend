from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.earnings.infrastructure.models import CompletedWorkORM
from app.modules.rates.application.timeline_service import FactoryPriceTimelineService
from app.modules.sync.domain.enums import SyncChangeType
from app.modules.sync.infrastructure.models import SyncChangeLogORM, SyncEventORM, SyncQueueItemORM
from app.shared.infrastructure.db.base import utcnow
from app.shared.infrastructure.db.uow_sqlalchemy import SqlAlchemyUnitOfWork
from test_factory_earnings import activate, assert_applied, case, earning, submit
from test_factory_price_timeline import confirmed, transition


def pull(case, cursor=0):
    response = case.client.post("/api/v1/installer/sync", json={"since_cursor": cursor, "events": []})
    assert response.status_code == 200, response.text
    return response.json()


def test_snapshot_exposes_only_active_confirmed_installer_prices_on_cold_and_warm_sync(case, db_session):
    db_session.add(SyncChangeLogORM(company_id=case.company, project_id=case.project, entity_id=case.project,
        installer_id=case.installer, change_type=SyncChangeType.PROJECT_BASE, payload={}, created_at=utcnow()))
    db_session.commit()
    assert pull(case)["factory_prices"] is None
    version = confirmed(case.company, case.actor, case.items)
    assert pull(case)["factory_prices"] is None  # Factory approval alone does not activate earnings.
    activation = transition(case.company, case.actor, version)
    cold = pull(case)
    prices = cold["factory_prices"]
    assert cold["reset_required"] is True
    assert set(prices) == {"price_list_id", "version", "currency", "effective_from", "items"}
    assert prices["price_list_id"] == str(version.id) and prices["version"] == 1
    assert prices["currency"] == "ILS"
    assert all(set(item) == {"kind", "target_id", "unit", "rate"} for item in prices["items"])
    assert {item["kind"]: Decimal(item["rate"]) for item in prices["items"]} == {
        "DOOR": Decimal("250"), "ADDON": Decimal("9")}
    warm = pull(case, cold["next_cursor"])
    assert warm["changes"] == [] and warm["factory_prices"] == prices
    v2, _ = activate(case, expected=1, previous=version.id, door_price="300")
    updated = pull(case, warm["next_cursor"])
    assert updated["factory_prices"]["price_list_id"] == str(v2.id)
    assert updated["factory_prices"]["effective_from"] != activation.effective_from.isoformat()


@pytest.mark.parametrize("kind", ["DOOR", "ADDON"])
@pytest.mark.parametrize("channel", ["sync", "batch"])
def test_cached_execution_version_survives_amendment_and_replay(case, db_session, kind, channel):
    v1, a1 = activate(case)
    activate(case, expected=1, previous=v1.id, door_price="300", addon_price="12")
    event_id, payload = str(uuid4()), {"price_list_id": str(v1.id)}
    for _ in range(2):
        assert_applied(submit(case, kind, channel, a1.effective_from, event_id, payload), channel)
    work, proof = earning(db_session, case)
    assert proof.price_list_id == v1.id
    assert work.amount_snapshot == (Decimal("250") if kind == "DOOR" else Decimal("13.50"))


@pytest.mark.parametrize("kind", ["DOOR", "ADDON"])
@pytest.mark.parametrize("channel", ["sync", "batch"])
def test_stale_cached_version_keeps_work_in_price_conflict_without_earning(case, db_session, kind, channel):
    v1, _ = activate(case)
    _, a2 = activate(case, expected=1, previous=v1.id)
    event_id, payload = str(uuid4()), {"price_list_id": str(v1.id)}
    for _ in range(2):
        response = submit(case, kind, channel, a2.effective_from, event_id, payload)
        assert response.status_code == 200, response.text
        result = response.json()["acks" if channel == "sync" else "results"][0]
        assert result["error" if channel == "sync" else "conflict_code"] == "CONFLICT_FACTORY_PRICE"
    db_session.expire_all()
    assert db_session.query(CompletedWorkORM).filter_by(company_id=case.company).count() == 0
    assert db_session.get(DoorORM, case.door).status == DoorStatus.IN_PROGRESS
    row = (db_session.query(SyncEventORM).filter_by(company_id=case.company, client_event_id=event_id).one()
           if channel == "sync" else db_session.get(SyncQueueItemORM, UUID(event_id)))
    assert row.payload["price_list_id"] == str(v1.id) and row.client_happened_at == a2.effective_from


@pytest.mark.parametrize("value", ["not-a-uuid", None, 123, {}, str(uuid4())])
def test_untrusted_version_cannot_select_prices_or_legacy_fallback(case, db_session, value):
    response = submit(case, "DOOR", "sync", utcnow(), extra_payload={"price_list_id": value})
    assert response.status_code == 200, response.text
    assert response.json()["acks"][0]["error"] == "CONFLICT_FACTORY_PRICE"
    assert db_session.query(CompletedWorkORM).filter_by(company_id=case.company).count() == 0


def test_old_mobile_undo_fields_are_not_price_authority_and_do_not_break_replay(case, db_session):
    version, activation = activate(case)
    event_id = str(uuid4())
    undo = {"previous_status": "IN_PROGRESS", "previous_reason_id": None,
            "previous_comment": "local only", "previous_is_locked": 0, "previous_version": 0,
            "price_list_id": str(version.id)}
    assert_applied(submit(case, "DOOR", "sync", activation.effective_from, event_id, undo), "sync")
    stripped = {key: undo[key] for key in ("previous_version", "price_list_id")}
    assert_applied(submit(case, "DOOR", "sync", activation.effective_from, event_id, stripped), "sync")
    assert earning(db_session, case)[0].amount_snapshot == Decimal("250")


def test_price_snapshot_is_company_scoped(case):
    activate(case)
    with SqlAlchemyUnitOfWork() as uow:
        assert FactoryPriceTimelineService.installer_snapshot(uow, company_id=uuid4()) is None


@pytest.mark.parametrize("applied", [False, True])
@pytest.mark.parametrize("field", ["price_list_id", "happened_at", "qty_done"])
def test_batch_reused_id_cannot_replace_execution_price_or_quantity(case, db_session, applied, field):
    version, activation = activate(case)
    event_id = str(uuid4())
    original_price = str(version.id if applied else uuid4())
    extra = {"price_list_id": original_price}
    submit(case, "ADDON", "batch", activation.effective_from, event_id, extra)
    at = utcnow() if field == "happened_at" else activation.effective_from
    if field == "price_list_id":
        extra["price_list_id"] = str(uuid4())
    if field == "qty_done":
        extra["qty_done"] = "2.00"
    response = submit(case, "ADDON", "batch", at, event_id, extra)
    assert response.status_code == 200, response.text
    assert response.json()["results"][0]["conflict_code"] == "CONFLICT_INVALID_TRANSITION"
    db_session.expire_all()
    row = db_session.get(SyncQueueItemORM, UUID(event_id))
    assert row.payload["price_list_id"] == original_price
    assert row.payload["qty_done"] == "1.50" and row.client_happened_at == activation.effective_from
    assert row.status == ("APPLIED" if applied else "CONFLICT")
    assert db_session.query(CompletedWorkORM).filter_by(company_id=case.company).count() == (1 if applied else 0)
