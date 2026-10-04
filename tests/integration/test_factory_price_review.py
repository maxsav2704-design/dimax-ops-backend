from datetime import timedelta
from uuid import uuid4

import pytest

from app.modules.addons.infrastructure.models import ProjectAddonFactORM
from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.earnings.infrastructure.models import CompletedWorkORM
from app.modules.sync.infrastructure.models import SyncEventORM, SyncQueueItemORM
from app.modules.identity.infrastructure.models import AdminProfileORM
from app.shared.domain.errors import Conflict
from test_factory_earnings import activate, case, submit


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


def test_review_legacy_uses_first_confirmed_price(case, db_session, client_admin_real_uow):
    row, url, v1, _ = conflict(case, db_session)
    row.payload = {key: value for key, value in row.payload.items() if key != "price_list_id"}
    row.client_happened_at -= timedelta(days=2)
    db_session.commit()
    data = client_admin_real_uow.get(url).json()
    assert data["analysis_code"] == "NO_VERSION"
    assert data["applicable_quote"]["price_list_id"] == str(v1.id)
    assert data["applicable_quote"]["selection"] == "FIRST_CONFIRMED_LEGACY"
    assert float(data["preview_amount"]) == 250


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
