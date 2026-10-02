from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.modules.addons.infrastructure.models import AddonTypeORM
from app.modules.audit.infrastructure.models import AuditLogORM
from app.modules.identity.domain.enums import UserRole
from app.modules.identity.infrastructure.models import AdminProfileORM, CompanyORM
from app.modules.rates.application.price_list_dto import CreatePriceList
from app.modules.rates.application.price_lists_service import FactoryPriceListsService
from app.modules.rates.infrastructure.price_list_models import FactoryPriceListItemORM, FactoryPriceListORM
from app.shared.domain.errors import Conflict
from app.shared.infrastructure.db.uow_sqlalchemy import SqlAlchemyUnitOfWork

URL = "/api/v1/admin/price-lists"


@pytest.fixture()
def draft(db_session, company_id, make_door_type):
    door_type = make_door_type(name="Entrance door")
    addon = AddonTypeORM(company_id=company_id, name="Adjustment", unit="hour")
    db_session.add(addon)
    db_session.commit()
    return {
        "request_id": str(uuid4()), "expected_latest_version": 0,
        "reason": "Initial factory offer", "agreement_reference": "Factory offer 2026-10-02",
        "items": [
            {"kind": "DOOR", "target_id": str(door_type.id), "installer_price": "250.00"},
            {"kind": "ADDON", "target_id": str(addon.id), "installer_price": "9.00"},
        ],
    }


def create(client, draft):
    response = client.post(URL, json=draft)
    assert response.status_code == 200, response.text
    return response.json()


def audit_rows(db_session, company_id):
    return db_session.scalars(select(AuditLogORM).where(
        AuditLogORM.company_id == company_id, AuditLogORM.entity_type == "FACTORY_PRICE_LIST",
    )).all()


def test_snapshot_versions_pagination_and_retry(client_admin_real_uow, draft, db_session, company_id):
    client = client_admin_real_uow
    first = create(client, draft)
    assert first["version"] == 1 and first["status"] == "DRAFT"
    assert first["currency"] == "ILS"
    assert [(item["name"], item["unit"], item["installer_price"]) for item in first["items"]] == [
        ("Adjustment", "hour", "9.00"), ("Entrance door", "pcs", "250.00"),
    ]
    retry = deepcopy(draft)
    retry["items"].reverse()
    retry["items"][0]["installer_price"] = "9"
    assert create(client, retry) == first
    second_body = deepcopy(draft)
    second_body.update(request_id=str(uuid4()), expected_latest_version=1, reason="Factory revised offer")
    second_body["items"][0]["installer_price"] = "300.00"
    second = create(client, second_body)
    assert second["version"] == 2
    assert create(client, draft) == first
    assert client.get(f'{URL}/{first["id"]}').json() == first
    page = client.get(URL, params={"limit": 1, "offset": 1}).json()
    assert page["total"] == 2 and page["latest_version"] == 2
    assert page["items"][0]["id"] == first["id"]
    assert "items" not in page["items"][0]
    assert len(audit_rows(db_session, company_id)) == 2


def test_catalog_rename_does_not_rewrite_snapshot(client, draft, db_session):
    first = create(client, draft)
    db_session.execute(text("UPDATE addon_types SET name = 'Renamed', unit = 'pcs' WHERE id = :id"),
                       {"id": draft["items"][1]["target_id"]})
    db_session.commit()
    assert create(client, draft) == first
    assert client.get(f'{URL}/{first["id"]}').json() == first


def test_audit_failure_rolls_back_whole_write(client, draft, db_session, company_id, monkeypatch):
    def fail_audit(*args, **kwargs):
        raise RuntimeError("Test audit failure")

    with monkeypatch.context() as patch:
        patch.setattr("app.modules.rates.application.price_lists_service.AuditService.add", fail_audit)
        response = client.post(URL, json=draft)
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert client.get(URL).json()["total"] == 0
    assert not audit_rows(db_session, company_id)
    created = create(client, draft)
    with monkeypatch.context() as patch:
        patch.setattr("app.modules.rates.application.price_lists_service.AuditService.add", fail_audit)
        response = client.post(f'{URL}/{created["id"]}/cancel', json={"reason": "Failed cancellation"})
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert client.get(f'{URL}/{created["id"]}').json() == created


def test_conflicting_request_and_stale_version_do_not_write(client, draft):
    create(client, draft)
    changed = deepcopy(draft)
    changed["items"][0]["installer_price"] = "400"
    assert client.post(URL, json=changed).status_code == 409
    changed["request_id"] = str(uuid4())
    assert client.post(URL, json=changed).status_code == 409
    assert client.get(URL).json()["total"] == 1


def test_cancel_preserves_history_and_no_edit_route(client, draft, db_session, company_id):
    original = create(client, draft)
    path = f'{URL}/{original["id"]}'
    response = client.post(f"{path}/cancel", json={"reason": "Factory requested another offer"})
    assert response.status_code == 200, response.text
    cancelled = response.json()
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["items"] == original["items"]
    assert cancelled["cancelled_by"] == original["created_by"]
    assert cancelled["cancelled_at"]
    assert client.post(f"{path}/cancel", json={"reason": "Retry"}).json() == cancelled
    assert create(client, draft) == cancelled
    assert client.patch(path, json={"items": []}).status_code == 405
    assert client.delete(path).status_code == 405
    assert len(audit_rows(db_session, company_id)) == 2


@pytest.mark.parametrize("price", ["0", "-1", "NaN", "Infinity", "0.001", "10000000000", True])
def test_invalid_money_is_rejected(client, draft, price):
    draft["items"][0]["installer_price"] = price
    response = client.post(URL, json=draft)
    assert response.status_code == 422, response.text
    assert client.get(URL).json()["total"] == 0


@pytest.mark.parametrize("field,value", [
    ("company_id", str(uuid4())), ("status", "APPROVED"), ("factory_approved", True),
    ("reason", "  "), ("agreement_reference", "\n"), ("expected_latest_version", True), ("items", []),
])
def test_forbidden_or_invalid_fields(client, draft, field, value):
    draft[field] = value
    assert client.post(URL, json=draft).status_code == 422
    assert client.get(URL).json()["total"] == 0


def test_duplicate_and_client_supplied_label_rejected(client, draft):
    duplicate = deepcopy(draft)
    duplicate["items"].append(duplicate["items"][0])
    assert client.post(URL, json=duplicate).status_code == 422
    draft["items"][0]["name"] = "Untrusted name"
    assert client.post(URL, json=draft).status_code == 422


@pytest.mark.parametrize("kind", ["DOOR", "ADDON"])
@pytest.mark.parametrize("unavailable", ["missing", "foreign", "inactive", "deleted"])
def test_unavailable_catalog_is_rejected(client, draft, db_session, kind, unavailable):
    item = next(item for item in draft["items"] if item["kind"] == kind)
    table = "door_types" if kind == "DOOR" else "addon_types"
    if unavailable == "missing":
        item["target_id"] = str(uuid4())
    else:
        assignment = {"foreign": "company_id = :foreign", "inactive": "is_active = false", "deleted": "deleted_at = now()"}[unavailable]
        # These catalog tables have no company FK; keep this fixture scoped and restore it for teardown.
        old_company = db_session.execute(text(f"SELECT company_id FROM {table} WHERE id = :id"), {"id": item["target_id"]}).scalar_one()
        db_session.execute(text(f"UPDATE {table} SET {assignment} WHERE id = :id"), {"id": item["target_id"], "foreign": uuid4()})
        db_session.commit()
    try:
        response = client.post(URL, json=draft)
        assert response.status_code == 422, response.text
        assert client.get(URL).json()["total"] == 0
    finally:
        if unavailable == "foreign":
            db_session.execute(text(f"UPDATE {table} SET company_id = :cid WHERE id = :id"), {"cid": old_company, "id": item["target_id"]})
            db_session.commit()


def test_other_tenant_not_found(client, client_raw, draft, db_session, make_user):
    original = create(client, draft)
    cid = uuid4()
    db_session.add(CompanyORM(id=cid, name="Other price-list test company", is_active=True))
    db_session.commit()
    try:
        user = make_user(company=cid, role=UserRole.ADMIN)
        login = client_raw.post("/api/v1/auth/login", json={
            "company_id": str(cid), "email": user.email, "password": "secret123", "device_id": "other-company",
        })
        assert login.status_code == 200, login.text
        headers = {"Authorization": f'Bearer {login.json()["access_token"]}'}
        assert client_raw.get(URL, headers=headers).json() == {"items": [], "total": 0, "latest_version": 0}
        path = f'{URL}/{original["id"]}'
        assert client_raw.get(path, headers=headers).status_code == 404
        assert client_raw.post(f"{path}/cancel", json={"reason": "Not mine"}, headers=headers).status_code == 404
        assert client_raw.post(URL, json=draft, headers=headers).status_code == 422
        assert client.get(path).json() == original
    finally:
        db_session.rollback()
        for table in ("audit_logs", "refresh_sessions", "admin_profiles", "users"):
            db_session.execute(text(f"DELETE FROM {table} WHERE company_id = :cid"), {"cid": cid})
        db_session.execute(text("DELETE FROM companies WHERE id = :cid"), {"cid": cid})
        db_session.commit()


@pytest.mark.parametrize("scope,view_rates,read_code,write_code", [
    ("OWNER", True, 200, 200), ("OPERATIONS", True, 200, 200),
    ("FINANCE", True, 200, 403), ("VIEWER", True, 403, 403),
    ("OPERATIONS", False, 403, 403), ("FINANCE", False, 403, 403),
    ("INSTALLER", False, 403, 403),
])
def test_real_jwt_access(client_raw, company_id, make_user, db_session, draft, scope, view_rates, read_code, write_code):
    password = "Factory-price-test-password-2026!"
    user = make_user(role=UserRole.INSTALLER if scope == "INSTALLER" else UserRole.ADMIN, password=password)
    if scope != "INSTALLER":
        profile = db_session.scalar(select(AdminProfileORM).where(AdminProfileORM.user_id == user.id))
        profile.admin_scope = scope
        profile.can_view_rates = view_rates
        db_session.commit()
    login = client_raw.post("/api/v1/auth/login", json={
        "company_id": str(company_id), "email": user.email, "password": password, "device_id": "factory-price-tests",
    })
    assert login.status_code == 200, login.text
    headers = {"Authorization": f'Bearer {login.json()["access_token"]}'}
    assert client_raw.get(URL, headers=headers).status_code == read_code
    response = client_raw.post(URL, json=draft, headers=headers)
    assert response.status_code == write_code, response.text
    target = response.json()["id"] if write_code == 200 else str(uuid4())
    cancelled = client_raw.post(f"{URL}/{target}/cancel", json={"reason": "Test cancellation"}, headers=headers)
    assert cancelled.status_code == write_code, cancelled.text


@pytest.mark.parametrize("same_request", [True, False])
def test_concurrent_creation_is_serialized(draft, admin_user, company_id, same_request):
    barrier = Barrier(2)
    bodies = [deepcopy(draft), deepcopy(draft)]
    if not same_request:
        bodies[1]["request_id"] = str(uuid4())

    def submit(body):
        barrier.wait(timeout=15)
        try:
            with SqlAlchemyUnitOfWork() as uow:
                uow.session.execute(text("SET LOCAL lock_timeout = '5s'"))
                result = FactoryPriceListsService.create(uow, company_id=company_id,
                    actor_user_id=admin_user.id, body=CreatePriceList.model_validate(body))
                return str(result.id)
        except Conflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, bodies))
    if same_request:
        assert results[0] == results[1] != "conflict"
    else:
        assert results.count("conflict") == 1
    with SqlAlchemyUnitOfWork() as uow:
        assert uow.price_lists.latest_version(company_id) == 1


@pytest.mark.parametrize("mutation", ["price", "target", "tenant", "duplicate", "nan"])
def test_database_line_constraints(client, draft, db_session, mutation):
    created = create(client, draft)
    row = db_session.scalar(select(FactoryPriceListItemORM).where(
        FactoryPriceListItemORM.price_list_id == UUID(created["id"]), FactoryPriceListItemORM.kind == "DOOR",
    ))
    constraint = {"price": "ck_factory_price_items_price", "nan": "ck_factory_price_items_price",
                  "target": "ck_factory_price_items_target", "tenant": "fk_factory_price_items_tenant_list",
                  "duplicate": "uq_factory_price_items_door"}[mutation]
    with pytest.raises(IntegrityError, match=constraint):
        with db_session.begin_nested():
            if mutation == "duplicate":
                db_session.add(FactoryPriceListItemORM(
                    company_id=row.company_id, price_list_id=row.price_list_id, kind=row.kind,
                    door_type_id=row.door_type_id, name=row.name, unit=row.unit, installer_price=row.installer_price,
                ))
            elif mutation == "price":
                row.installer_price = Decimal("-1")
            elif mutation == "target":
                row.kind = "ADDON"
            elif mutation == "tenant":
                row.company_id = uuid4()
            elif mutation == "nan":
                row.installer_price = Decimal("NaN")
            db_session.flush()


@pytest.mark.parametrize("field,value,constraint", [
    ("version", 0, "ck_factory_price_lists_version"),
    ("status", "APPROVED", "ck_factory_price_lists_status"),
    ("status", "CANCELLED", "ck_factory_price_lists_status"),
    ("currency", "USD", "ck_factory_price_lists_currency"),
])
def test_database_version_constraints(client, draft, db_session, field, value, constraint):
    created = create(client, draft)
    row = db_session.get(FactoryPriceListORM, UUID(created["id"]))
    with pytest.raises(IntegrityError, match=constraint):
        with db_session.begin_nested():
            setattr(row, field, value)
            db_session.flush()


def test_drafts_do_not_touch_legacy_payroll(client, draft, db_session, company_id, make_installer):
    from app.modules.doors.infrastructure.models import DoorORM
    from app.modules.earnings.infrastructure.models import CompletedWorkORM
    from app.modules.projects.infrastructure.models import ProjectORM
    from app.modules.rates.infrastructure.models import InstallerRateORM
    installer = make_installer()
    rate = InstallerRateORM(company_id=company_id, installer_id=installer.id,
                            door_type_id=UUID(draft["items"][0]["target_id"]), price=Decimal("125.00"))
    db_session.add(rate)
    project = ProjectORM(company_id=company_id, name="Existing work", address="Test", status="OK")
    db_session.add(project)
    db_session.flush()
    door = DoorORM(company_id=company_id, project_id=project.id,
                   door_type_id=rate.door_type_id, installer_id=installer.id,
                   unit_label="A-101", status="INSTALLED", is_locked=True, our_price=Decimal("300"))
    db_session.add(door)
    db_session.flush()
    db_session.add(CompletedWorkORM(company_id=company_id, project_id=project.id,
        door_id=door.id, installer_id=installer.id, completed_at=datetime.now(timezone.utc),
        quantity=Decimal("1"), rate_snapshot=Decimal("125"), amount_snapshot=Decimal("125")))
    db_session.commit()
    tables = ("installer_rates", "project_addon_plans", "completed_work", "doors", "sync_change_log")

    def snapshot():
        return {table: db_session.execute(text(
            f"SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text), '[]'::jsonb) FROM {table} t WHERE company_id = :cid"
        ), {"cid": company_id}).scalar_one() for table in tables}

    before = snapshot()
    created = create(client, draft)
    assert client.post(f'{URL}/{created["id"]}/cancel', json={"reason": "Unapproved offer"}).status_code == 200
    db_session.expire_all()
    assert snapshot() == before
    assert db_session.get(InstallerRateORM, rate.id).price == Decimal("125.00")


def test_openapi_declares_drafts_and_secured_errors(client_raw):
    spec = client_raw.get("/openapi.json").json()
    for path, method in ((URL, "get"), (URL, "post"), (URL + "/{price_list_id}", "get"),
                         (URL + "/{price_list_id}/cancel", "post")):
        operation = spec["paths"][path][method]
        assert {"200", "401", "403", "404", "409", "422"}.issubset(operation["responses"])
        assert operation["security"]
    schemas = spec["components"]["schemas"]
    assert schemas["CreatePriceList"]["additionalProperties"] is False
    assert schemas["PriceListLineInput"]["additionalProperties"] is False
    assert schemas["PriceListDetail"]["properties"]["status"]["enum"] == ["DRAFT", "CANCELLED", "CONFIRMED"]


def test_full_length_reason_survives_create_and_cancel_audit(client, draft, db_session, company_id):
    draft["reason"] = "R" * 1000
    created = create(client, draft)
    assert created["reason"] == draft["reason"]
    reason = "C" * 1000
    response = client.post(f'{URL}/{created["id"]}/cancel', json={"reason": reason})
    assert response.status_code == 200, response.text
    assert response.json()["cancellation_reason"] == reason
    rows = audit_rows(db_session, company_id)
    assert {row.after["reason"] for row in rows} == {draft["reason"], reason}
    assert all(len(row.reason) == 500 for row in rows)
