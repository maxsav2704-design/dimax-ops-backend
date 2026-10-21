from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
import os
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError

from app.api.v1.deps import require_admin
from app.modules.accounting.application.dto import CreateContractTermsDraft
from app.modules.accounting.application.service import CommercialDraftService
from app.modules.accounting.infrastructure.models import (
    CommercialContractORM, CommercialContractTermsORM, CommercialPriceItemORM, CommercialPriceVersionORM,
)
from app.modules.audit.infrastructure.models import AuditLogORM
from app.modules.earnings.infrastructure.models import CompletedWorkORM
from app.modules.identity.infrastructure.models import CompanyORM, AdminProfileORM, UserORM
from app.modules.rates.infrastructure.models import InstallerRateORM
from app.modules.rates.infrastructure.price_list_models import FactoryPriceListORM
from app.shared.domain.errors import Conflict
from app.shared.infrastructure.db.uow_sqlalchemy import SqlAlchemyUnitOfWork
# Reuse the established commercial contract fixtures, not their tests/teardown.
from tests.integration.test_commercial_drafts import owner_client, contract_body, contract, create_contract, URL


@pytest.fixture(autouse=True)
def isolated_terms(db_session, company_id):
    assert os.environ.get("APP_ENV") == "test"
    assert db_session.scalar(text("SELECT current_database()")).endswith("_tests")
    yield
    db_session.rollback()
    # Test teardown only; production writes cannot bypass immutable history.
    db_session.execute(text("SET LOCAL session_replication_role = 'replica'"))
    for model in (CommercialContractTermsORM, CommercialPriceItemORM, CommercialPriceVersionORM, CommercialContractORM):
        db_session.execute(delete(model).where(model.company_id == company_id))
    db_session.commit()


@pytest.fixture()
def terms_body():
    return {
        "request_id": str(uuid4()), "expected_latest_version": 0,
        "factory_legal_name": "Synthetic Factory Ltd", "registration_number": "TEST-123",
        "address": "Synthetic address only", "contact_name": "Test contact",
        "contact_email": "contract@example.com", "contact_phone": "+972 50 000 0000",
        "proposed_from": "2026-11-10", "proposed_until": None, "billing_basis": "STAGES",
        "payment_terms": "Synthetic: 30 calendar days after delivery of the signed journals.",
        "retention_terms": "Synthetic: no retention.", "reason": "Synthetic preparation",
        "agreement_reference": "TEST ONLY, not a factory agreement",
    }


def path(contract):
    return f'{URL}/{contract["id"]}/terms'


def save(client, contract, body):
    response = client.post(path(contract), json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_versions_replay_history_audit_and_no_financial_writes(owner_client, contract, terms_body, db_session, company_id):
    models = (InstallerRateORM, CompletedWorkORM, FactoryPriceListORM, CommercialPriceVersionORM)
    before = [db_session.scalar(select(func.count()).select_from(model)) for model in models]
    first = save(owner_client, contract, terms_body)
    assert first["version"] == 1 and first["created_by_name"]
    assert first["is_demo"] and first["status"] == "DRAFT"
    assert not first["factory_confirmed"] and not first["usable_for_billing"]
    assert (first["period_start_day"], first["period_timezone"], first["vat_basis"]) == (10, "Asia/Jerusalem", "EXCLUSIVE")
    assert save(owner_client, contract, terms_body) == first
    second = {**terms_body, "request_id": str(uuid4()), "expected_latest_version": 1,
              "address": "Amended address", "retention_terms": "Synthetic amendment", "reason": "New draft"}
    newer = save(owner_client, contract, second)
    assert newer["version"] == 2
    db_session.execute(text("UPDATE users SET full_name='Changed later' WHERE id=:id"), {"id": first["created_by"]})
    db_session.commit()
    assert owner_client.get(path(contract) + '/' + first["id"]).json() == first
    assert save(owner_client, contract, terms_body) == first
    listing = owner_client.get(path(contract), params={"limit": 1, "offset": 1})
    assert listing.headers["cache-control"] == "no-store"
    page = listing.json()
    assert page["total"] == page["latest_version"] == 2 and page["items"][0]["id"] == first["id"]
    assert "contact_email" not in page["items"][0]
    assert [db_session.scalar(select(func.count()).select_from(model)) for model in models] == before
    events = db_session.scalars(select(AuditLogORM).where(AuditLogORM.company_id == company_id,
                                                        AuditLogORM.entity_type == "COMMERCIAL_TERMS")).all()
    assert len(events) == 2


@pytest.mark.parametrize("field,value", [
    ("factory_legal_name", "  "), ("registration_number", ""), ("address", "x" * 1001),
    ("payment_terms", ""), ("retention_terms", "x" * 4001), ("reason", ""), ("agreement_reference", ""),
    ("contact_email", "invalid"), ("contact_phone", "---"), ("contact_name", ""),
    ("proposed_until", "2026-11-09"), ("billing_basis", "BOTH"), ("expected_latest_version", True),
    ("company_id", str(uuid4())), ("is_demo", False), ("status", "CONFIRMED"),
    ("created_by_name", "Forged"), ("period_start_day", 1), ("currency", "USD"),
])
def test_invalid_and_forged_fields(owner_client, contract, terms_body, field, value):
    assert owner_client.post(path(contract), json={**terms_body, field: value}).status_code == 422
    assert owner_client.get(path(contract)).json()["total"] == 0


def test_optional_contact_and_end(owner_client, contract, terms_body):
    for field in ("contact_name", "contact_email", "contact_phone", "proposed_until"):
        terms_body.pop(field)
    terms_body["billing_basis"] = "FULL_INSTALLATION"
    first = save(owner_client, contract, terms_body)
    assert first["contact_email"] is None and first["proposed_until"] is None


def test_conflicts_and_contract_scoping(owner_client, contract, terms_body, contract_body):
    first = save(owner_client, contract, terms_body)
    assert owner_client.post(path(contract), json={**terms_body, "reason": "Altered"}).status_code == 409
    assert owner_client.post(path(contract), json={**terms_body, "request_id": str(uuid4())}).status_code == 409
    second_contract = create_contract(owner_client, {**contract_body, "request_id": str(uuid4()), "reference": "SECOND"})
    assert owner_client.get(path(second_contract) + '/' + first["id"]).status_code == 404
    assert owner_client.post(path(second_contract), json=terms_body).status_code == 409
    assert owner_client.get(path(second_contract)).json()["total"] == 0


def test_history_cannot_be_updated_deleted_or_activated(owner_client, contract, terms_body, db_session):
    first = save(owner_client, contract, terms_body)
    url = path(contract) + '/' + first["id"]
    assert owner_client.patch(url, json={"retention_terms": "changed"}).status_code == 405
    assert owner_client.delete(url).status_code == 405
    assert owner_client.post(url + '/activate', json={}).status_code == 404
    for sql in ("UPDATE commercial_contract_terms SET address='changed' WHERE id=:id",
                "DELETE FROM commercial_contract_terms WHERE id=:id"):
        with pytest.raises(IntegrityError), db_session.begin_nested():
            db_session.execute(text(sql), {"id": first["id"]})
    assert owner_client.get(url).json() == first


@pytest.mark.parametrize("scope", ["OPERATIONS", "FINANCE", "VIEWER"])
def test_live_revoked_owner(owner_client, contract, terms_body, db_session, admin_user, scope):
    first = save(owner_client, contract, terms_body)
    db_session.execute(text("UPDATE admin_profiles SET admin_scope=:scope WHERE user_id=:id"), {"scope": scope, "id": admin_user.id})
    db_session.commit()
    assert owner_client.get(path(contract)).status_code == 403
    assert owner_client.get(path(contract) + '/' + first["id"]).status_code == 403
    assert owner_client.post(path(contract), json=terms_body).status_code == 403


def test_installer_anonymous_and_foreign_owner(owner_client, contract, terms_body, client_installer, client_raw,
                                             make_user, db_session, admin_user):
    first = save(owner_client, contract, terms_body)
    assert client_installer.get(path(contract)).status_code == 403
    assert client_installer.post(path(contract), json=terms_body).status_code == 403
    assert client_raw.get(path(contract)).status_code in (401, 403)
    foreign = uuid4()
    db_session.add(CompanyORM(id=foreign, name="Synthetic foreign", is_active=True))
    db_session.commit()
    user = make_user(company=foreign, role="ADMIN")
    override = owner_client.app.dependency_overrides[require_admin]
    owner_client.app.dependency_overrides[require_admin] = lambda: replace(
        admin_user, id=user.id, company_id=foreign, admin_scope="OWNER",
    )
    try:
        assert owner_client.get(path(contract)).status_code == 404
        assert owner_client.get(path(contract) + '/' + first["id"]).status_code == 404
        assert owner_client.post(path(contract), json=terms_body).status_code == 404
    finally:
        owner_client.app.dependency_overrides[require_admin] = override
        db_session.execute(delete(AdminProfileORM).where(AdminProfileORM.user_id == user.id))
        db_session.execute(delete(UserORM).where(UserORM.id == user.id))
        db_session.execute(delete(CompanyORM).where(CompanyORM.id == foreign))
        db_session.commit()


def test_audit_failure_is_atomic(owner_client, contract, terms_body, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("Synthetic audit failure")
    with monkeypatch.context() as patch:
        patch.setattr("app.modules.accounting.application.service.AuditService.add", fail)
        assert owner_client.post(path(contract), json=terms_body).status_code == 500
    assert owner_client.get(path(contract)).json()["total"] == 0
    save(owner_client, contract, terms_body)


@pytest.mark.parametrize("same_request", [True, False])
def test_concurrent_terms(owner_client, contract, terms_body, admin_user, same_request):
    barrier = Barrier(2)
    def run(index):
        body = deepcopy(terms_body)
        if not same_request:
            body["request_id"] = str(uuid4())
        barrier.wait(timeout=15)
        try:
            with SqlAlchemyUnitOfWork() as uow:
                return CommercialDraftService.create_terms(uow, admin_user, UUID(contract["id"]), CreateContractTermsDraft(**body)).id
        except Conflict:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    if same_request:
        assert results[0] == results[1] != "conflict"
    else:
        assert results.count("conflict") == 1
    assert owner_client.get(path(contract)).json()["total"] == 1
