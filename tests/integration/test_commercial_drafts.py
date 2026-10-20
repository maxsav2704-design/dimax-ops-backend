from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError

from app.api.v1.deps import get_current_user, require_admin
from app.modules.accounting.application.dto import CreateCommercialPriceDraft
from app.modules.accounting.application.service import CommercialDraftService
from app.modules.accounting.infrastructure.models import (
    CommercialContractORM, CommercialPriceItemORM, CommercialPriceVersionORM,
)
from app.modules.addons.infrastructure.models import AddonTypeORM
from app.modules.audit.infrastructure.models import AuditLogORM
from app.modules.door_types.infrastructure.models import DoorTypeORM
from app.modules.earnings.infrastructure.models import CompletedWorkORM
from app.modules.identity.infrastructure.models import CompanyORM
from app.modules.rates.infrastructure.price_list_models import FactoryPriceListORM
from app.shared.domain.errors import Conflict
from app.shared.infrastructure.db.uow_sqlalchemy import SqlAlchemyUnitOfWork

URL = "/api/v1/admin/accounting/contracts"
DEMO = json.loads((Path(__file__).parents[1] / "fixtures/commercial_demo_prices.json").read_text())


@pytest.fixture(autouse=True)
def isolated_drafts(db_session, company_id):
    assert os.environ.get("APP_ENV") == "test"
    assert db_session.scalar(text("SELECT current_database()")).endswith("_tests")
    yield
    db_session.rollback()
    for model in (CommercialPriceItemORM, CommercialPriceVersionORM, CommercialContractORM):
        db_session.execute(delete(model).where(model.company_id == company_id))
    db_session.commit()


@pytest.fixture()
def owner_client(client_admin_real_uow, admin_user):
    client_admin_real_uow.app.dependency_overrides[require_admin] = lambda: replace(
        admin_user, admin_scope="OWNER",
    )
    return client_admin_real_uow


@pytest.fixture()
def contract_body():
    return {"request_id": str(uuid4()), "factory_name": DEMO["factory_name"],
            "reference": DEMO["reference"], "reason": DEMO["notice"]}


def create_contract(client, body):
    response = client.post(URL, json=body)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture()
def contract(owner_client, contract_body):
    return create_contract(owner_client, contract_body)


@pytest.fixture()
def price_body(make_door_type, db_session, company_id):
    door = make_door_type(name="DEMO entrance")
    addon = AddonTypeORM(company_id=company_id, name="DEMO additional adjustment", unit="hour")
    db_session.add(addon)
    db_session.commit()
    return {
        "request_id": str(uuid4()), "expected_latest_version": 0,
        "proposed_from": DEMO["proposed_from"], "reason": DEMO["notice"],
        "agreement_reference": "DEMO only; no factory agreement",
        "items": [{**line, "target_id": str(addon.id if line["kind"] == "ADDON" else door.id)}
                  for line in DEMO["items"]],
    }


def prices_url(contract):
    return f'{URL}/{contract["id"]}/prices'


def create_price(client, contract, body):
    response = client.post(prices_url(contract), json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_draft_versions_replay_and_separate_finances(owner_client, contract, price_body, db_session, company_id):
    counts_before = [db_session.scalar(select(func.count()).select_from(model).where(
        model.company_id == company_id,
    )) for model in (CompletedWorkORM, FactoryPriceListORM)]
    first = create_price(owner_client, contract, price_body)
    assert contract["status"] == first["status"] == "DRAFT"
    assert contract["is_demo"] and first["is_demo"]
    assert not first["factory_confirmed"] and not first["usable_for_billing"]
    assert first["vat_basis"] == "EXCLUSIVE"
    retry = deepcopy(price_body)
    retry["items"].reverse()
    retry["items"][0]["unit_price_ex_vat"] = "60"
    assert create_price(owner_client, contract, retry) == first
    second = deepcopy(price_body)
    second.update(request_id=str(uuid4()), expected_latest_version=1, reason="DEMO amendment")
    second["items"][0]["unit_price_ex_vat"] = "410.00"
    newer = create_price(owner_client, contract, second)
    assert newer["version"] == 2
    path = f'{prices_url(contract)}/{first["id"]}'
    assert owner_client.get(path).json() == first
    page = owner_client.get(prices_url(contract), params={"limit": 1, "offset": 1}).json()
    assert page["total"] == page["latest_version"] == 2
    assert page["items"][0]["id"] == first["id"]
    assert "items" not in page["items"][0]
    for index, model in enumerate((CompletedWorkORM, FactoryPriceListORM)):
        assert db_session.scalar(select(func.count()).select_from(model).where(
            model.company_id == company_id,
        )) == counts_before[index]
    assert owner_client.patch(path, json={"status": "CONFIRMED"}).status_code == 405
    assert owner_client.post(f"{path}/activate", json={}).status_code == 404


def test_contract_replay_conflicts_and_page(owner_client, contract_body):
    first = create_contract(owner_client, contract_body)
    assert create_contract(owner_client, contract_body) == first
    changed = {**contract_body, "factory_name": "Different"}
    assert owner_client.post(URL, json=changed).status_code == 409
    changed["request_id"] = str(uuid4())
    assert owner_client.post(URL, json=changed).status_code == 409
    assert owner_client.get(URL).json() == {"items": [first], "total": 1}


def test_price_key_conflict_and_optimistic_version(owner_client, contract, price_body):
    first = create_price(owner_client, contract, price_body)
    price_body["items"][0]["unit_price_ex_vat"] = "401"
    assert owner_client.post(prices_url(contract), json=price_body).status_code == 409
    price_body["request_id"] = str(uuid4())
    assert owner_client.post(prices_url(contract), json=price_body).status_code == 409
    assert owner_client.get(f'{prices_url(contract)}/{first["id"]}').json() == first


@pytest.mark.parametrize("value", ["-1", "NaN", "Infinity", "0.001", "10000000000", True])
def test_invalid_money(owner_client, contract, price_body, value):
    price_body["items"][0]["unit_price_ex_vat"] = value
    assert owner_client.post(prices_url(contract), json=price_body).status_code == 422
    assert owner_client.get(prices_url(contract)).json()["total"] == 0


def test_explicit_zero_is_preserved(owner_client, contract, price_body):
    price_body["items"][0]["unit_price_ex_vat"] = "0"
    result = create_price(owner_client, contract, price_body)
    assert next(line for line in result["items"] if line["kind"] == "INSTALLATION")["unit_price_ex_vat"] == "0.00"


@pytest.mark.parametrize("field,value", [
    ("company_id", str(uuid4())), ("status", "CONFIRMED"), ("is_demo", False),
    ("factory_confirmed", True), ("currency", "USD"), ("reason", "  "),
    ("items", []), ("expected_latest_version", True),
])
def test_server_fields_and_invalid_input(owner_client, contract, price_body, field, value):
    price_body[field] = value
    assert owner_client.post(prices_url(contract), json=price_body).status_code == 422


@pytest.mark.parametrize("case", ["duplicate", "stage_missing", "stage_on_complete", "bad_stage", "missing_price"])
def test_invalid_lines(owner_client, contract, price_body, case):
    if case == "duplicate":
        price_body["items"].append(price_body["items"][0])
    elif case == "stage_missing":
        price_body["items"][1]["stage_code"] = ""
    elif case == "stage_on_complete":
        price_body["items"][0]["stage_code"] = "FRAME"
    elif case == "bad_stage":
        price_body["items"][1]["stage_code"] = "frame!"
    else:
        del price_body["items"][0]["unit_price_ex_vat"]
    assert owner_client.post(prices_url(contract), json=price_body).status_code == 422


@pytest.mark.parametrize("scope", ["OPERATIONS", "FINANCE", "VIEWER", None])
def test_scope_and_revocation(owner_client, admin_user, db_session, contract, price_body, scope):
    # The route override remains OWNER; the service must re-read the real profile.
    db_session.execute(text("UPDATE admin_profiles SET admin_scope=:scope WHERE user_id=:uid"),
                       {"scope": scope or "VIEWER", "uid": admin_user.id})
    db_session.commit()
    for response in (
        owner_client.get(URL),
        owner_client.get(prices_url(contract)),
        owner_client.post(prices_url(contract), json=price_body),
    ):
        assert response.status_code == 403


def test_installer_and_unauthenticated_blocked(client_installer, client_raw, contract_body):
    assert client_installer.get(URL).status_code == 403
    assert client_installer.post(URL, json=contract_body).status_code == 403
    assert client_raw.get(URL).status_code in {401, 403}


@pytest.mark.parametrize("scope", ["OWNER", "OPERATIONS", "FINANCE", "VIEWER", "INSTALLER"])
def test_real_jwt_authority(client_raw, company_id, make_user, db_session, contract_body, scope):
    from app.modules.identity.domain.enums import UserRole
    from app.modules.identity.infrastructure.models import AdminProfileORM

    password = "Commercial-draft-synthetic-password-2026!"
    user = make_user(role=UserRole.INSTALLER if scope == "INSTALLER" else UserRole.ADMIN,
                     password=password)
    if scope != "INSTALLER":
        profile = db_session.scalar(select(AdminProfileORM).where(AdminProfileORM.user_id == user.id))
        profile.admin_scope = scope
        profile.can_view_rates = True
        db_session.commit()
    login = client_raw.post("/api/v1/auth/login", json={
        "company_id": str(company_id), "email": user.email, "password": password,
        "device_id": "commercial-draft-tests",
    })
    assert login.status_code == 200, login.text
    headers = {"Authorization": f'Bearer {login.json()["access_token"]}'}
    expected = 200 if scope == "OWNER" else 403
    response = client_raw.post(URL, json=contract_body, headers=headers)
    assert response.status_code == expected, response.text
    listing = client_raw.get(URL, headers=headers)
    assert listing.status_code == expected
    if scope == "OWNER":
        assert listing.headers["cache-control"] == "no-store"
        assert listing.json()["items"][0]["id"] == response.json()["id"]
        profile.admin_scope = "VIEWER"
        db_session.commit()
        assert client_raw.get(URL, headers=headers).status_code == 403


def test_valid_foreign_owner_gets_not_found(owner_client, admin_user, contract, price_body,
                                          db_session, make_user):
    from app.modules.identity.domain.enums import UserRole
    from app.modules.identity.infrastructure.models import AdminProfileORM, UserORM

    first = create_price(owner_client, contract, price_body)
    foreign_id = uuid4()
    db_session.add(CompanyORM(id=foreign_id, name="DEMO second tenant", is_active=True))
    db_session.commit()
    foreign_user = make_user(company=foreign_id, role=UserRole.ADMIN)
    original_override = owner_client.app.dependency_overrides.pop(require_admin)
    owner_client.app.dependency_overrides[get_current_user] = lambda: replace(
        admin_user, id=foreign_user.id, company_id=foreign_id, admin_scope="OWNER",
    )
    try:
        assert owner_client.get(URL).json()["items"] == []
        assert owner_client.get(prices_url(contract)).status_code == 404
        assert owner_client.get(f'{prices_url(contract)}/{first["id"]}').status_code == 404
        assert owner_client.post(prices_url(contract), json=price_body).status_code == 404
    finally:
        owner_client.app.dependency_overrides.pop(get_current_user)
        owner_client.app.dependency_overrides[require_admin] = original_override
        db_session.execute(delete(AdminProfileORM).where(AdminProfileORM.user_id == foreign_user.id))
        db_session.execute(delete(UserORM).where(UserORM.id == foreign_user.id))
        db_session.execute(delete(CompanyORM).where(CompanyORM.id == foreign_id))
        db_session.commit()


def test_inactive_company_cannot_create(owner_client, company_id, contract, price_body, db_session):
    db_session.execute(text("UPDATE companies SET is_active=false WHERE id=:id"), {"id": company_id})
    db_session.commit()
    assert owner_client.post(prices_url(contract), json=price_body).status_code == 403


def test_wrong_tenant_cannot_read_or_write(owner_client, contract, price_body, db_session, admin_user):
    foreign_id = uuid4()
    db_session.add(CompanyORM(id=foreign_id, name="DEMO foreign", is_active=True))
    db_session.commit()
    foreign_type = DoorTypeORM(company_id=foreign_id, code="demo-foreign", name="Foreign", is_active=True)
    db_session.add(foreign_type)
    db_session.commit()
    try:
        body = deepcopy(price_body)
        body["items"][0]["target_id"] = str(foreign_type.id)
        assert owner_client.post(prices_url(contract), json=body).status_code == 422
        assert owner_client.get(prices_url(contract)).json()["total"] == 0
        first = create_price(owner_client, contract, price_body)
        # Authenticated principal with a mismatched tenant is rejected by live membership.
        owner_client.app.dependency_overrides[require_admin] = lambda: replace(
            admin_user, company_id=foreign_id, admin_scope="OWNER",
        )
        assert owner_client.get(f'{prices_url(contract)}/{first["id"]}').status_code == 403
    finally:
        db_session.execute(delete(DoorTypeORM).where(DoorTypeORM.id == foreign_type.id))
        db_session.execute(delete(CompanyORM).where(CompanyORM.id == foreign_id))
        db_session.commit()


def test_inactive_catalog_and_snapshot(owner_client, contract, price_body, db_session):
    first = create_price(owner_client, contract, price_body)
    db_session.execute(text("UPDATE door_types SET name='Renamed', is_active=false WHERE id=:id"),
                       {"id": price_body["items"][0]["target_id"]})
    db_session.commit()
    assert owner_client.get(f'{prices_url(contract)}/{first["id"]}').json() == first
    price_body.update(request_id=str(uuid4()), expected_latest_version=1)
    assert owner_client.post(prices_url(contract), json=price_body).status_code == 422


def test_audit_failure_rolls_back(owner_client, contract, price_body, monkeypatch, db_session, company_id):
    def fail(*args, **kwargs):
        raise RuntimeError("Synthetic audit failure")
    with monkeypatch.context() as patch:
        patch.setattr("app.modules.accounting.application.service.AuditService.add", fail)
        assert owner_client.post(prices_url(contract), json=price_body).status_code == 500
    assert owner_client.get(prices_url(contract)).json()["total"] == 0
    assert not db_session.scalars(select(AuditLogORM).where(
        AuditLogORM.company_id == company_id, AuditLogORM.entity_type == "COMMERCIAL_PRICE",
    )).all()
    create_price(owner_client, contract, price_body)


@pytest.mark.parametrize("same_request", [True, False])
def test_concurrent_creation(owner_client, contract, price_body, admin_user, same_request):
    barrier = Barrier(2)
    def run(index):
        body = deepcopy(price_body)
        if not same_request:
            body["request_id"] = str(uuid4())
        barrier.wait(timeout=10)
        try:
            with SqlAlchemyUnitOfWork() as uow:
                return CommercialDraftService.create_price(
                    uow, admin_user, UUID(contract["id"]), CreateCommercialPriceDraft(**body),
                ).id
        except Conflict:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    if same_request:
        assert results[0] == results[1] != "conflict"
    else:
        assert results.count("conflict") == 1
    assert owner_client.get(prices_url(contract)).json()["total"] == 1


def test_db_cannot_promote_draft(owner_client, contract, price_body, db_session):
    first = create_price(owner_client, contract, price_body)
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.execute(text("UPDATE commercial_price_versions SET status='CONFIRMED' WHERE id=:id"),
                           {"id": first["id"]})
    assert owner_client.get(f'{prices_url(contract)}/{first["id"]}').json() == first


def test_openapi_contract(owner_client):
    spec = owner_client.get("/openapi.json").json()
    for path, methods in (
        (URL, ("get", "post")), (URL + "/{contract_id}/prices", ("get", "post")),
        (URL + "/{contract_id}/prices/{price_id}", ("get",)),
    ):
        for method in methods:
            responses = spec["paths"][path][method]["responses"]
            assert {"200", "400", "401", "403", "404", "409", "422"} <= responses.keys()
            assert "$ref" in responses["200"]["content"]["application/json"]["schema"]
