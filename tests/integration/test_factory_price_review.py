from datetime import timedelta
from uuid import uuid4

import pytest

from decimal import Decimal

from app.modules.addons.infrastructure.models import AddonTypeORM, ProjectAddonFactORM, ProjectAddonPlanORM
from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.earnings.infrastructure.models import CompletedWorkORM
from app.modules.sync.infrastructure.models import SyncEventORM, SyncQueueItemORM
from app.modules.identity.infrastructure.models import AdminProfileORM
from app.shared.domain.errors import Conflict
from test_factory_earnings import activate, case, submit
from test_factory_price_timeline import confirmed
from app.modules.sync.application.price_review_service import PriceConflictReviewService
from app.shared.infrastructure.db.base import utcnow


def conflict(case, db, kind="DOOR", channel="batch"):
    v1, _ = activate(case)
    try:
        v2, a2 = activate(case, expected=1, previous=v1.id, door_price="300", addon_price="12")
    except Conflict as exc:
        pytest.fail(f"Conflict fixture activation failed: {exc}; {exc.meta}")
    event_id = str(uuid4())
    response = submit(case, kind, channel, a2.effective_from, event_id,
                      {"price_list_id": str(v1.id)})
    assert response.status_code == 200, response.text
    model = SyncEventORM if channel == "sync" else SyncQueueItemORM
    row = db.query(model).filter_by(company_id=case.company).one()
    source = "sync_event" if channel == "sync" else "sync_queue"
    assert (row.apply_error if channel == "sync" else row.conflict_code) == "CONFLICT_FACTORY_PRICE"
    return row, f"/api/v1/admin/sync/price-conflicts/{source}/{row.id}", v1, v2


@pytest.mark.parametrize("kind", ["DOOR", "ADDON"])
@pytest.mark.parametrize("channel", ["sync", "batch"])
def test_review_uses_execution_price_without_mutating_work(case, db_session, client_admin_real_uow, kind, channel):
    row, url, v1, v2 = conflict(case, db_session, kind, channel)
    activate(case, expected=2, previous=v2.id, door_price="400", addon_price="20")
    original = (row.payload.copy(), row.client_happened_at,
                row.apply_error if channel == "sync" else (row.status, row.conflict_code))
    for _ in range(2):
        response = client_admin_real_uow.get(url)
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["analysis_code"] == "VERSION_MISMATCH"
        assert data["seen_price_list_id"] == str(v1.id)
        assert data["seen_version"] == 1
        assert data["applicable_quote"]["price_list_id"] == str(v2.id)
        assert data["applicable_quote"]["version"] == 2
        assert float(data["preview_amount"]) == (300 if kind == "DOOR" else 18)
        assert data["resolution_available"] is (kind == "ADDON" or channel == "batch")
        assert data["work_context"] == "CURRENT_CATALOG"
    db_session.expire_all()
    assert (row.payload, row.client_happened_at,
            row.apply_error if channel == "sync" else (row.status, row.conflict_code)) == original
    assert db_session.query(CompletedWorkORM).filter_by(company_id=case.company).count() == 0
    assert db_session.query(ProjectAddonFactORM).filter_by(company_id=case.company).count() == 0
    assert db_session.get(DoorORM, case.door).status == DoorStatus.IN_PROGRESS


@pytest.mark.parametrize("channel", ["sync", "batch"])
def test_review_requires_live_rate_permission(case, db_session, client_admin_real_uow, channel):
    _, url, _, _ = conflict(case, db_session, channel=channel)
    profile = db_session.query(AdminProfileORM).filter_by(user_id=case.actor).one()
    profile.can_view_rates = False
    db_session.commit()
    assert client_admin_real_uow.get(url).status_code == 403
    assert case.client.get(url).status_code == 403


@pytest.mark.parametrize("channel", ["sync", "batch"])
def test_review_hides_foreign_records(case, db_session, client_admin_real_uow, channel):
    row, url, _, _ = conflict(case, db_session, channel=channel)
    # Query under another tenant without changing a stored record's ownership.
    from app.api.v1.deps import CurrentUser, require_admin
    client_admin_real_uow.app.dependency_overrides[require_admin] = lambda: CurrentUser(
        id=case.actor, company_id=uuid4(), role="ADMIN")
    assert client_admin_real_uow.get(url).status_code in (403, 404)
    from app.modules.sync.application.price_review_service import PriceConflictReviewService
    from app.shared.domain.errors import NotFound
    from app.shared.infrastructure.db.uow_sqlalchemy import SqlAlchemyUnitOfWork
    with SqlAlchemyUnitOfWork() as uow, pytest.raises(NotFound):
        PriceConflictReviewService.get(uow, company_id=uuid4(), item_id=row.id,
            source="sync_event" if channel == "sync" else "sync_queue")


@pytest.mark.parametrize("scope,rates,expected", [
    ("OWNER", True, 200), ("OPERATIONS", True, 200), ("OPERATIONS", False, 403),
    ("FINANCE", True, 403), ("VIEWER", True, 403), ("INSTALLER", False, 403),
])
def test_real_jwt_review_access(case, db_session, client_raw, make_user, scope, rates, expected):
    from app.modules.identity.domain.enums import UserRole
    _, url, _, _ = conflict(case, db_session)
    user = make_user(role=UserRole.INSTALLER if scope == "INSTALLER" else UserRole.ADMIN)
    if scope != "INSTALLER":
        profile = db_session.query(AdminProfileORM).filter_by(user_id=user.id).one()
        profile.admin_scope, profile.can_view_rates = scope, rates
        db_session.commit()
    assert client_raw.get(url).status_code == 401
    login = client_raw.post("/api/v1/auth/login", json={"company_id": str(case.company),
        "email": user.email, "password": "secret123", "device_id": "price-review-test"})
    assert login.status_code == 200, login.text
    response = client_raw.get(url, headers={"Authorization": f'Bearer {login.json()["access_token"]}'})
    assert response.status_code == expected, response.text


@pytest.mark.parametrize("field,value,code", [
    ("client_happened_at", None, "MISSING_EXECUTION_TIME"),
    ("project_id", uuid4(), "WORK_UNAVAILABLE"),
    ("quantity", "bad", "INVALID_QUANTITY"),
    ("quantity", "NaN", "INVALID_QUANTITY"),
])
def test_review_never_guesses_missing_data(case, db_session, client_admin_real_uow, field, value, code):
    row, url, _, _ = conflict(case, db_session, kind="ADDON")
    if field == "quantity":
        row.payload = {**row.payload, "qty_done": value}
    else:
        setattr(row, field, value)
    db_session.commit()
    response = client_admin_real_uow.get(url)
    assert response.status_code == 200, response.text
    assert response.json()["analysis_code"] == code
    assert response.json()["preview_amount"] is None


def test_review_does_not_quote_impossible_precreation_time(case, db_session, client_admin_real_uow):
    row, url, v1, _ = conflict(case, db_session)
    row.payload = {key: value for key, value in row.payload.items() if key != "price_list_id"}
    row.client_happened_at -= timedelta(days=2)
    db_session.commit()
    data = client_admin_real_uow.get(url).json()
    assert data["analysis_code"] == "INVALID_EXECUTION_TIME"
    assert data["applicable_quote"] is None
    assert data["resolution_available"] is False


@pytest.mark.parametrize("channel", ["sync", "batch"])
def test_only_unresolved_price_conflicts_are_reviewable(case, db_session, client_admin_real_uow, channel):
    row, url, _, _ = conflict(case, db_session, channel=channel)
    if channel == "sync":
        row.apply_error = None
    else:
        row.status = "APPLIED"
    db_session.commit()
    assert client_admin_real_uow.get(url).status_code == 404


def test_price_filter_queries_both_sources_before_limit(case, db_session, client_admin_real_uow):
    row, _, v1, v2 = conflict(case, db_session, channel="sync")
    response = submit(case, "ADDON", "batch", row.client_happened_at,
                      extra_payload={"price_list_id": str(v1.id)})
    assert response.status_code == 200
    # A newer unrelated conflict must not crowd a price conflict out of the limit.
    queue = db_session.query(SyncQueueItemORM).filter_by(company_id=case.company).one()
    db_session.add(SyncQueueItemORM(company_id=case.company, user_id=queue.user_id,
        entity_type="door", entity_id=case.door, operation_type="DOOR_SET_STATUS",
        project_id=case.project, payload={}, base_version=0, status="CONFLICT",
        conflict_code="CONFLICT_VERSION", created_at=queue.created_at + timedelta(seconds=1)))
    db_session.commit()
    path = "/api/v1/admin/sync/problems?status=price_conflict"
    data = client_admin_real_uow.get(path + "&limit=1").json()
    assert data["total"] == 2
    assert len(data["items"]) == 1
    data = client_admin_real_uow.get(path + f"&installer_id={case.installer}").json()
    assert {item["source"] for item in data["items"]} == {"sync_event", "sync_queue"}
    assert all(item["problem_code"] == "CONFLICT_FACTORY_PRICE" and item["retry_allowed"] is False
               for item in data["items"])
    assert client_admin_real_uow.get(path + f"&installer_id={uuid4()}").json()["total"] == 0


@pytest.mark.parametrize("kind", ["DOOR", "ADDON"])
@pytest.mark.parametrize("channel", ["sync", "batch"])
@pytest.mark.parametrize("legacy", [False, True])
def test_missing_price_evidence_survives_later_list_and_retries(
    case, db_session, client_admin_real_uow, make_door_type, kind, channel, legacy,
):
    from test_offline_execution_authority import retained

    if legacy:
        at = utcnow()
        first = confirmed(case.company, case.actor, [item for item in case.items if item["kind"] != kind])
        latest, activation = activate(case, expected=1)
    else:
        first, activation = activate(case)
        if kind == "DOOR":
            target = make_door_type(name="New work without a factory price").id
            db_session.get(DoorORM, case.door).door_type_id = target
            case.door_type = target
        else:
            target_row = AddonTypeORM(company_id=case.company, name="Unpriced additional work", unit="pcs")
            db_session.add(target_row)
            db_session.flush()
            target = target_row.id
            # The office plans the work; only the factory price is missing.
            db_session.add(ProjectAddonPlanORM(
                company_id=case.company, project_id=case.project, addon_type_id=target,
                qty_planned=Decimal("1"), client_price=Decimal("20"), installer_price=Decimal("0"),
            ))
            case.addon = target
        db_session.commit()
        case.items.append({"kind": kind, "target_id": target, "installer_price": "700"})
        at = utcnow()
        latest = first

    payload = {"base_version": 0} if kind == "DOOR" else {}
    event_id = str(uuid4())
    assert submit(case, kind, channel, at, event_id, payload).status_code == 200
    row, url = retained(db_session, case, channel)
    source = "sync_event" if channel == "sync" else "sync_queue"
    original = PriceConflictReviewService.original(row, source)

    for later in (False, True):
        if later:
            activate(case, expected=latest.version, previous=latest.id, door_price="800", addon_price="40")
        response = client_admin_real_uow.get(url)
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["analysis_code"] == "MISSING_FACTORY_PRICE"
        assert data["resolution_available"] is False
        assert data["applicable_quote"] is data["preview_amount"] is data["review_token"] is None
        evidence = data["missing_price"]
        assert evidence["price_list_id"] == str(first.id)
        assert evidence["version"] == first.version
        assert evidence["activation_id"] == str(activation.id)
        assert evidence["kind"] == kind
        assert evidence["target_id"] == str(case.door_type if kind == "DOOR" else case.addon)
        assert evidence["selection"] == ("FIRST_CONFIRMED_LEGACY" if legacy else "AT_EXECUTION")
        assert evidence["performed_at"] == at.isoformat().replace("+00:00", "Z")
        assert len(evidence["snapshot_hash"]) == 64
        assert not {"rate", "amount", "price_list_item_id"} & evidence.keys()
        assert client_admin_real_uow.post(url + "/resolve", json={
            "request_id": str(uuid4()), "review_token": "0" * 64,
            "reason": "No factory price: manual bypass must not work", "confirm_execution_evidence": True,
        }).status_code == 409
        assert submit(case, kind, channel, at, event_id, payload).status_code == 200
        retained(db_session, case, channel)
        db_session.refresh(row)
        assert PriceConflictReviewService.original(row, source) == original
        assert db_session.query(ProjectAddonFactORM).filter_by(company_id=case.company).count() == 0


@pytest.mark.parametrize("channel", ["sync", "batch"])
def test_no_missing_price_evidence_when_factory_receipt_is_invalid(case, db_session, client_admin_real_uow, channel):
    from app.modules.rates.infrastructure.approval_models import FactoryPriceApprovalORM
    from test_offline_execution_authority import retained

    at = utcnow()
    first = confirmed(case.company, case.actor, case.items[:1])
    activate(case, expected=1)
    submit(case, "ADDON", channel, at)
    _, url = retained(db_session, case, channel)
    assert client_admin_real_uow.get(url).json()["missing_price"]["price_list_id"] == str(first.id)
    receipt = db_session.query(FactoryPriceApprovalORM).filter_by(company_id=case.company, price_list_id=first.id).one()
    # Simulate corrupted authority; absence of a rate must not disguise failed receipt verification.
    receipt.snapshot = {**receipt.snapshot, "company_name": "Corrupt evidence"}
    db_session.commit()
    data = client_admin_real_uow.get(url).json()
    assert data["analysis_code"] == "INVALID_FACTORY_EVIDENCE"
    assert data["missing_price"] is data["applicable_quote"] is None
    retained(db_session, case, channel)
