from datetime import datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.modules.earnings.infrastructure.models import CompletedWorkORM
from app.modules.identity.infrastructure.models import AdminProfileORM, UserORM
from app.modules.rates.infrastructure.approval_models import FactoryPriceApprovalORM
from app.modules.rates.infrastructure.timeline_models import FactoryPriceActivationORM
from app.modules.sync.infrastructure.models import SyncPriceResolutionORM
from test_factory_price_timeline import book, other_admin, quote, transition
from test_factory_price_application_check import confirm_version
from test_factory_earnings import case, submit, assert_applied
from test_price_conflict_resolution import clean_test_decisions

URL = "/api/v1/admin/price-lists"


def body(previous=None, **changes):
    return {"request_id": str(uuid4()), "expected_active_price_list_id": str(previous) if previous else None,
            "reason": "Reviewed company-wide transition", "reviewed_transition": True, **changes}


def login(client, db_session, user_id):
    user = db_session.get(UserORM, user_id)
    response = client.post("/api/v1/auth/login", json={"company_id": str(user.company_id),
        "email": user.email, "password": "secret123", "device_id": "activation-api-qa"})
    assert response.status_code == 200, response.text
    client.headers["Authorization"] = f'Bearer {response.json()["access_token"]}'


def test_activation_endpoint_is_repeat_safe_and_updates_state(client, book, company_id, db_session):
    request = body()
    path = f"{URL}/{book[3].id}/activate"
    response = client.post(path, json=request)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert client.post(path, json=request).json() == response.json()
    assert client.get(f"{URL}/state").json()["active_price"]["price_list_id"] == str(book[3].id)
    assert len(db_session.scalars(select(FactoryPriceActivationORM).where(
        FactoryPriceActivationORM.company_id == company_id)).all()) == 1
    assert client.post(path, json={**request, "reason": "Changed request"}).status_code == 409


@pytest.mark.parametrize("changes", [
    {"reviewed_transition": False}, {"reviewed_transition": "true"}, {"reason": " "},
    {"effective_from": "2000-01-01T00:00:00Z"}, {"installer_price": "999"}, {"company_id": str(uuid4())},
])
def test_activation_rejects_unreviewed_backdated_or_overridden_requests(client, book, changes):
    response = client.post(f"{URL}/{book[3].id}/activate", json=body(**changes))
    assert response.status_code == 422, response.text
    assert client.get(f"{URL}/state").json()["mode"] == "LEGACY"


@pytest.mark.parametrize("mode", ["FINANCE", "VIEWER", "no_rates", "inactive"])
def test_activation_route_checks_database_permissions(client, book, admin_user, db_session, mode):
    profile = db_session.scalar(select(AdminProfileORM).where(AdminProfileORM.user_id == admin_user.id))
    if mode in ("FINANCE", "VIEWER"):
        profile.admin_scope = mode
    elif mode == "no_rates":
        profile.can_view_rates = False
    else:
        db_session.get(UserORM, admin_user.id).is_active = False
    db_session.commit()
    assert client.post(f"{URL}/{book[3].id}/activate", json=body()).status_code == 403


def test_installer_and_anonymous_cannot_activate(client_installer, client_raw, book):
    path = f"{URL}/{book[3].id}/activate"
    assert client_installer.post(path, json=body()).status_code == 403
    assert client_raw.post(path, json=body()).status_code == 401


def test_foreign_admin_cannot_activate_another_company_list(client_raw, book, other_admin, db_session):
    login(client_raw, db_session, other_admin[1])
    assert client_raw.post(f"{URL}/{book[3].id}/activate", json=body()).status_code == 404


def test_latest_check_cannot_be_bypassed_with_stale_ui(client, book, make_door_type):
    assert client.get(f"{URL}/{book[3].id}/reconciliation").json()["application_check"]["blockers"] == []
    make_door_type(name="Added after administrator review")
    response = client.post(f"{URL}/{book[3].id}/activate", json=body())
    assert response.status_code == 409
    assert "MISSING_DOOR_PRICES" in response.text
    assert client.get(f"{URL}/state").json()["mode"] == "LEGACY"


def test_unverified_historical_decision_cannot_be_newly_activated(client, book, db_session):
    receipt = db_session.scalar(select(FactoryPriceApprovalORM).where(FactoryPriceApprovalORM.price_list_id == book[3].id))
    receipt.mailbox_verified_at = None
    db_session.commit()
    response = client.post(f"{URL}/{book[3].id}/activate", json=body())
    assert response.status_code == 409
    assert "MAILBOX_NOT_VERIFIED" in response.text
    assert client.get(f"{URL}/state").json()["mode"] == "LEGACY"


def test_historical_effective_receipt_remains_readable_without_backfilled_evidence(book, company_id, admin_user, db_session):
    activation = transition(company_id, admin_user.id, book[3])
    receipt = db_session.scalar(select(FactoryPriceApprovalORM).where(FactoryPriceApprovalORM.price_list_id == book[3].id))
    receipt.mailbox_verified_at = None
    db_session.commit()
    assert quote(company_id, book[0].id, activation.effective_from).rate == Decimal("250")
    db_session.refresh(receipt)
    assert receipt.mailbox_verified_at is None


def test_authenticated_factory_activation_to_reviewed_late_offline_earnings(case, client_raw, db_session, installer_user):
    login(client_raw, db_session, case.actor)
    items = [{**item, "target_id": str(item["target_id"])} for item in case.items]
    first = confirm_version(client_raw, items)
    first_activation = client_raw.post(f'{URL}/{first["id"]}/activate', json=body())
    assert first_activation.status_code == 200, first_activation.text
    performed_at = datetime.fromisoformat(first_activation.json()["effective_from"])
    next_list = confirm_version(client_raw, [{**item, "installer_price": "300" if item["kind"] == "DOOR" else "12"}
                                             for item in items], expected=1)
    assert client_raw.post(f'{URL}/{next_list["id"]}/activate', json=body()).status_code == 409
    activated = client_raw.post(f'{URL}/{next_list["id"]}/activate', json=body(first["id"]))
    assert activated.status_code == 200, activated.text
    login(client_raw, db_session, installer_user.id)
    assert client_raw.post(f'{URL}/{next_list["id"]}/activate', json=body()).status_code == 403
    case.client = client_raw
    pending = []
    for kind in ("DOOR", "ADDON"):
        event = str(uuid4())
        for _ in range(2):
            response = submit(case, kind, "batch", performed_at, event, {"price_list_id": first["id"]})
            assert response.status_code == 200, response.text
            result = response.json()["results"][0]
            assert result["status"] == "CONFLICT" and result["conflict_code"] == "CONFLICT_FACTORY_PRICE"
        path = f"/api/v1/admin/sync/price-conflicts/sync_queue/{event}"
        assert client_raw.get(path).status_code == 403
        assert client_raw.post(path + "/resolve", json={"request_id": str(uuid4()),
            "review_token": "0" * 64, "reason": "Installer cannot authorize own historical earnings",
            "confirm_execution_evidence": True}).status_code == 403
        pending.append((kind, event, path))
    assert db_session.query(CompletedWorkORM).filter_by(company_id=case.company).count() == 0

    login(client_raw, db_session, case.actor)
    for _, _, path in pending:
        response = client_raw.get(path)
        assert response.status_code == 200, response.text
        review = response.json()
        assert review["analysis_code"] == "HISTORICAL_PRICE_REVIEW"
        assert review["requires_execution_evidence"] and review["resolution_available"]
        request = {"request_id": str(uuid4()), "review_token": review["review_token"],
            "reason": "Verified assignment and completed work against the site work record"}
        assert client_raw.post(path + "/resolve", json=request).status_code == 409
        request["confirm_execution_evidence"] = True
        resolved = client_raw.post(path + "/resolve", json=request)
        assert resolved.status_code == 200, resolved.text
        assert client_raw.post(path + "/resolve", json=request).json() == resolved.json()

    login(client_raw, db_session, installer_user.id)
    for kind, event, _ in pending:
        assert_applied(submit(case, kind, "batch", performed_at, event, {"price_list_id": first["id"]}), "batch")
    db_session.expire_all()
    rows = db_session.scalars(select(CompletedWorkORM).where(CompletedWorkORM.company_id == case.company)).all()
    assert sorted(row.amount_snapshot for row in rows) == [Decimal("13.50"), Decimal("250.00")]
    assert all(row.completed_at == performed_at for row in rows)
    decisions = db_session.query(SyncPriceResolutionORM).filter_by(company_id=case.company).all()
    assert len(decisions) == 2
    assert all(row.actor_user_id == case.actor and row.quote_snapshot["execution_evidence_confirmed"]
               for row in decisions)
