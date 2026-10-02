from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text

from app.modules.rates.application.approval_dto import ConfirmApproval
from app.modules.rates.application.approval_service import FactoryPriceApprovalService
from app.modules.rates.infrastructure.approval_models import FactoryPriceApprovalORM
from app.shared.infrastructure.db.base import utcnow
from app.shared.infrastructure.db.uow_sqlalchemy import SqlAlchemyUnitOfWork

ADMIN = "/api/v1/admin/price-lists"
PUBLIC = "/api/v1/public/price-approvals"


@pytest.fixture()
def approval_case(client, make_door_type):
    door_type = make_door_type(name="Entrance")
    draft = {"request_id": str(uuid4()), "expected_latest_version": 0, "reason": "Factory offer",
             "agreement_reference": "Offer 42", "items": [
                 {"kind": "DOOR", "target_id": str(door_type.id), "installer_price": "250.00"}]}
    created = client.post(ADMIN, json=draft)
    assert created.status_code == 200, created.text
    price_list = created.json()
    invitation_body = {"factory_name": "Test Factory", "recipient_name": "Test Representative",
                       "recipient_email": "factory@example.com", "expires_in_hours": 24}
    issued = client.post(f'{ADMIN}/{price_list["id"]}/approvals', json=invitation_body)
    assert issued.status_code == 200, issued.text
    link = issued.json()
    return {"draft": draft, "price_list": price_list, "issued": link,
            "body": invitation_body, "token": urlsplit(link["confirmation_url"]).fragment}


def preview(client, case):
    return client.post(f"{PUBLIC}/preview", json={"token": case["token"]})


def confirmation(client, case):
    response = preview(client, case)
    assert response.status_code == 200, response.text
    return {"token": case["token"], "expected_version": response.json()["version"],
            "snapshot_hash": response.json()["snapshot_hash"], "signer_name": "Test Representative", "accepted": True}


def test_public_confirmation_is_explicit_private_and_repeat_safe(client, client_raw, approval_case, db_session):
    case = approval_case
    view = preview(client_raw, case)
    assert view.status_code == 200, view.text
    assert view.headers["cache-control"] == "no-store"
    data = view.json()
    assert data["status"] == "PENDING" and data["affects_earnings"] is False
    assert data["items"] == [{"kind": "DOOR", "name": "Entrance", "unit": "pcs", "installer_price": "250.00"}]
    for forbidden in ("recipient_email", "company_id", "created_by", "target_id", "token_hash", "project_id"):
        assert forbidden not in view.text
    assert client.get(f'{ADMIN}/{case["price_list"]["id"]}').json()["status"] == "DRAFT"
    body = confirmation(client_raw, case)
    signed = client_raw.post(f"{PUBLIC}/confirm", json=body)
    assert signed.status_code == 200, signed.text
    assert signed.json()["status"] == "CONFIRMED"
    assert signed.json()["confirmed_name"] == body["signer_name"]
    assert client_raw.post(f"{PUBLIC}/confirm", json=body).json() == signed.json()
    assert client.get(f'{ADMIN}/{case["price_list"]["id"]}').json()["status"] == "CONFIRMED"
    assert client.post(f'{ADMIN}/{case["price_list"]["id"]}/cancel', json={"reason": "Undo"}).status_code == 409
    assert client.post(f'{ADMIN}/{case["price_list"]["id"]}/approvals', json=case["body"]).status_code == 409
    row = db_session.get(FactoryPriceApprovalORM, UUID(case["issued"]["invitation"]["id"]))
    assert len(row.token_hash) == 64 and case["token"] not in str(row.__dict__)
    history = client.get(f'{ADMIN}/{case["price_list"]["id"]}/approvals')
    assert history.json()["total"] == 1
    assert history.json()["items"][0]["confirmed_name"] == body["signer_name"]
    assert case["token"] not in history.text and "token_hash" not in history.text
    body["signer_name"] = "Different signer"
    assert client_raw.post(f"{PUBLIC}/confirm", json=body).status_code == 409


@pytest.mark.parametrize("change,value,code", [
    ("accepted", False, 422), ("accepted", "true", 422), ("accepted", 1, 422),
    ("expected_version", 999, 409), ("snapshot_hash", "0" * 64, 409),
    ("signer_name", " ", 422), ("company_id", str(uuid4()), 422), ("installer_price", "999", 422),
])
def test_bad_confirmation_cannot_change_status(client, client_raw, approval_case, change, value, code):
    body = confirmation(client_raw, approval_case)
    body[change] = value
    assert client_raw.post(f"{PUBLIC}/confirm", json=body).status_code == code
    assert client.get(f'{ADMIN}/{approval_case["price_list"]["id"]}').json()["status"] == "DRAFT"


@pytest.mark.parametrize("mode", ["revoke", "rotate", "expire", "cancel", "new_version", "inactive_company"])
def test_unusable_links_cannot_preview_or_confirm(client, client_raw, approval_case, db_session, company_id, mode):
    case = approval_case
    body = confirmation(client_raw, case)
    base = f'{ADMIN}/{case["price_list"]["id"]}'
    if mode == "revoke":
        path = f'{base}/approvals/{case["issued"]["invitation"]["id"]}/revoke'
        first = client.post(path, json={"reason": "Wrong recipient"})
        assert first.status_code == 200
        assert client.post(path, json={"reason": "Retry"}).json() == first.json()
    elif mode == "rotate":
        assert client.post(f"{base}/approvals", json=case["body"]).status_code == 200
    elif mode == "expire":
        row = db_session.get(FactoryPriceApprovalORM, UUID(case["issued"]["invitation"]["id"]))
        row.created_at = utcnow() - timedelta(days=2)
        row.expires_at = utcnow() - timedelta(days=1)
        db_session.commit()
    elif mode == "cancel":
        assert client.post(f"{base}/cancel", json={"reason": "Withdraw offer"}).status_code == 200
    elif mode == "new_version":
        changed = {**case["draft"], "request_id": str(uuid4()), "expected_latest_version": 1}
        assert client.post(ADMIN, json=changed).status_code == 200
    else:
        db_session.execute(text("UPDATE companies SET is_active=false WHERE id=:cid"), {"cid": company_id})
        db_session.commit()
    code = 409 if mode == "new_version" else 404
    try:
        assert preview(client_raw, case).status_code == code
        assert client_raw.post(f"{PUBLIC}/confirm", json=body).status_code == code
    finally:
        if mode == "inactive_company":
            db_session.execute(text("UPDATE companies SET is_active=true WHERE id=:cid"), {"cid": company_id})
            db_session.commit()


def test_snapshot_tampering_blocks_confirmation(client_raw, approval_case, db_session):
    body = confirmation(client_raw, approval_case)
    db_session.execute(text("UPDATE factory_price_list_items SET installer_price=999 WHERE price_list_id=:id"),
                       {"id": approval_case["price_list"]["id"]})
    db_session.commit()
    assert client_raw.post(f"{PUBLIC}/confirm", json=body).status_code == 409
    assert preview(client_raw, approval_case).status_code == 409


def test_confirmation_is_atomic_and_does_not_touch_payroll(client, client_raw, approval_case, db_session, company_id):
    tables = ("installer_rates", "completed_work", "project_addon_plans", "sync_change_log")
    def snapshot():
        return {name: db_session.execute(text(
            f"SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text), '[]'::jsonb) FROM {name} t WHERE company_id=:cid"
        ), {"cid": company_id}).scalar_one() for name in tables}
    before = snapshot()
    body = confirmation(client_raw, approval_case)
    with patch.object(FactoryPriceApprovalService, "_public", side_effect=RuntimeError("Test rollback")):
        assert client_raw.post(f"{PUBLIC}/confirm", json=body).status_code == 500
    assert preview(client_raw, approval_case).json()["status"] == "PENDING"
    assert client.get(f'{ADMIN}/{approval_case["price_list"]["id"]}').json()["status"] == "DRAFT"
    assert client_raw.post(f"{PUBLIC}/confirm", json=body).status_code == 200
    assert snapshot() == before


def test_concurrent_confirmation_is_single_decision(client_raw, approval_case, db_session):
    body = ConfirmApproval.model_validate(confirmation(client_raw, approval_case))
    barrier = Barrier(2)
    def confirm():
        barrier.wait(timeout=15)
        with SqlAlchemyUnitOfWork() as uow:
            uow.session.execute(text("SET LOCAL lock_timeout='5s'"))
            return FactoryPriceApprovalService.confirm(uow, body=body).model_dump(mode="json")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: confirm(), range(2)))
    assert results[0] == results[1]
    row = db_session.get(FactoryPriceApprovalORM, UUID(approval_case["issued"]["invitation"]["id"]))
    assert row.confirmed_at is not None and row.confirmed_name == body.signer_name


def test_link_actions_denied_to_installer(client_installer, approval_case):
    base = f'{ADMIN}/{approval_case["price_list"]["id"]}/approvals'
    assert client_installer.get(base).status_code == 403
    assert client_installer.post(base, json=approval_case["body"]).status_code == 403
    assert client_installer.post(f'{base}/{approval_case["issued"]["invitation"]["id"]}/revoke',
                                 json={"reason": "No"}).status_code == 403


def test_unknown_tokens_rate_limit_and_get_never_confirms(client_raw):
    token = "A" * 43
    for _ in range(60):
        assert client_raw.post(f"{PUBLIC}/preview", json={"token": token}).status_code == 404
    assert client_raw.post(f"{PUBLIC}/preview", json={"token": token}).status_code == 429
    assert client_raw.get(f"{PUBLIC}/confirm").status_code == 405


def test_new_draft_does_not_revoke_existing_factory_decision(client, client_raw, approval_case):
    body = confirmation(client_raw, approval_case)
    result = client_raw.post(f"{PUBLIC}/confirm", json=body)
    assert result.status_code == 200
    new_draft = {**approval_case["draft"], "request_id": str(uuid4()), "expected_latest_version": 1}
    new_draft["items"][0]["installer_price"] = "300.00"
    assert client.post(ADMIN, json=new_draft).status_code == 200
    assert preview(client_raw, approval_case).json() == result.json()
    assert client_raw.post(f"{PUBLIC}/confirm", json=body).json() == result.json()


def test_revoke_racing_confirmation_has_one_winner(client_raw, approval_case, admin_user, company_id):
    from app.shared.domain.errors import Conflict, NotFound
    body = ConfirmApproval.model_validate(confirmation(client_raw, approval_case))
    barrier = Barrier(2)
    def run(action):
        barrier.wait(timeout=15)
        try:
            with SqlAlchemyUnitOfWork() as uow:
                uow.session.execute(text("SET LOCAL lock_timeout='5s'"))
                if action == "confirm":
                    FactoryPriceApprovalService.confirm(uow, body=body)
                else:
                    FactoryPriceApprovalService.revoke(uow, company_id=company_id,
                        price_list_id=UUID(approval_case["price_list"]["id"]),
                        approval_id=UUID(approval_case["issued"]["invitation"]["id"]),
                        actor_user_id=admin_user.id, reason="Concurrent withdrawal")
                return "ok"
        except Conflict:
            return "conflict"
        except NotFound:
            return "unavailable"
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(run, ("confirm", "revoke")))
    assert result in (["ok", "conflict"], ["unavailable", "ok"])


@pytest.mark.parametrize("scope,read_code", [("FINANCE", 200), ("VIEWER", 403), ("OPERATIONS", 403)])
def test_real_admin_scopes_for_links(client_raw, approval_case, make_user, company_id, db_session, scope, read_code):
    from app.modules.identity.domain.enums import UserRole
    from app.modules.identity.infrastructure.models import AdminProfileORM
    user = make_user(role=UserRole.ADMIN)
    profile = db_session.scalar(select(AdminProfileORM).where(AdminProfileORM.user_id == user.id))
    profile.admin_scope = scope
    profile.can_view_rates = scope != "OPERATIONS"
    db_session.commit()
    login = client_raw.post("/api/v1/auth/login", json={"company_id": str(company_id),
        "email": user.email, "password": "secret123", "device_id": "factory-scope-test"})
    assert login.status_code == 200, login.text
    headers = {"Authorization": f'Bearer {login.json()["access_token"]}'}
    path = f'{ADMIN}/{approval_case["price_list"]["id"]}/approvals'
    assert client_raw.get(path, headers=headers).status_code == read_code
    assert client_raw.post(path, headers=headers, json=approval_case["body"]).status_code == 403
    assert client_raw.post(f'{path}/{approval_case["issued"]["invitation"]["id"]}/revoke',
                          headers=headers, json={"reason": "Not allowed"}).status_code == 403
