from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Event, current_thread, main_thread
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.modules.addons.application.use_cases import AddonsUseCases
from app.modules.addons.infrastructure.models import AddonTypeORM, ProjectAddonPlanORM, ProjectUrgencySurchargeORM
from app.modules.rates.application.timeline_dto import ActivatePriceVersion
from app.modules.rates.application.timeline_service import FactoryPriceTimelineService
from app.modules.rates.infrastructure.price_lists_repository import FactoryPriceListsRepository
from app.modules.rates.infrastructure.approval_models import FactoryPriceApprovalORM
from app.shared.domain.errors import Conflict
from app.shared.infrastructure.db.uow_sqlalchemy import SqlAlchemyUnitOfWork
from test_factory_earnings import case, activate, confirmed, submit, earning


def plan_request(client, case, channel, *, price=None, include_price=False, addon_id=None):
    payload = {"addon_type_id": str(addon_id or case.addon), "qty_planned": "5", "client_price": "30", "notes": "Updated scope"}
    if include_price:
        payload["installer_price"] = price
    if channel == "legacy":
        return client.put(f"/api/v1/admin/addons/projects/{case.project}/plan", json=payload)
    path = f"/api/v1/admin/projects/{case.project}/addons/plan"
    return client.put(path, json={"items": [payload]}) if channel == "batch" else client.post(path, json=payload)


@pytest.mark.parametrize("channel", ["single", "batch", "legacy"])
def test_factory_plan_updates_scope_not_price(case, client_admin_real_uow, db_session, channel):
    activate(case)
    response = plan_request(client_admin_real_uow, case, channel)
    assert response.status_code == 200, response.text
    rows = response.json()["plan" if channel == "batch" else "items"]
    assert Decimal(rows[0]["installer_price"]) == Decimal("9")
    db_session.expire_all()
    plan = db_session.get(ProjectAddonPlanORM, case.plan)
    assert (plan.qty_planned, plan.client_price, plan.installer_price, plan.notes) == (
        Decimal("5"), Decimal("30"), Decimal("999"), "Updated scope")
    response = plan_request(client_admin_real_uow, case, channel, price="200", include_price=True)
    assert response.status_code == 409, response.text
    assert response.json()["error"]["meta"]["reason"] == "FACTORY_ADDON_PRICE_REQUIRED"
    db_session.expire_all()
    assert db_session.get(ProjectAddonPlanORM, case.plan).installer_price == Decimal("999")


@pytest.mark.parametrize("channel", ["single", "batch", "legacy"])
def test_confirmation_only_preserves_legacy_price_requirement(case, client_admin_real_uow, channel):
    confirmed(case.company, case.actor, case.items)
    assert plan_request(client_admin_real_uow, case, channel).status_code == 422
    assert plan_request(client_admin_real_uow, case, channel, price="12", include_price=True).status_code == 200


def test_catalog_and_unpriced_plan_never_claim_zero_as_confirmed(case, client_admin_real_uow, db_session):
    activate(case)
    client = client_admin_real_uow
    response = client.post("/api/v1/admin/addons/types", json={"name": "New work", "default_installer_price": "20"})
    assert response.status_code == 409, response.text
    response = client.post("/api/v1/admin/addons/types", json={"name": "New work"})
    assert response.status_code == 200, response.text
    addon = response.json()
    assert addon["default_installer_price"] is None
    response = plan_request(client, case, "single", addon_id=addon["id"])
    assert response.status_code == 200, response.text
    assert next(row for row in response.json()["items"] if row["addon_type_id"] == addon["id"])["installer_price"] is None
    types = client.get("/api/v1/admin/addons/types").json()["items"]
    assert Decimal(next(row for row in types if row["id"] == str(case.addon))["default_installer_price"]) == Decimal("9")
    assert db_session.query(AddonTypeORM).filter_by(company_id=case.company, name="New work").count() == 1


def test_new_plan_does_not_store_factory_price_in_legacy_column(case, client_admin_real_uow, db_session):
    db_session.delete(db_session.get(ProjectAddonPlanORM, case.plan))
    db_session.commit()
    activate(case)
    response = plan_request(client_admin_real_uow, case, "single")
    assert response.status_code == 200, response.text
    plan = db_session.query(ProjectAddonPlanORM).filter_by(company_id=case.company, project_id=case.project).one()
    assert plan.installer_price == 0
    assert Decimal(response.json()["items"][0]["installer_price"]) == Decimal("9")


def test_summary_uses_earned_snapshots_not_new_plan_or_new_factory_price(case, client_admin_real_uow, db_session):
    v1, _ = activate(case)
    assert submit(case, "ADDON", "direct").status_code == 200
    before, proof = earning(db_session, case)
    evidence = (before.id, before.amount_snapshot, proof.price_list_id)
    activate(case, expected=1, previous=v1.id, addon_price="12")
    assert plan_request(client_admin_real_uow, case, "single").status_code == 200
    response = client_admin_real_uow.get(f"/api/v1/admin/projects/{case.project}/addons")
    assert response.status_code == 200, response.text
    assert Decimal(response.json()["plan"][0]["installer_price"]) == Decimal("12")
    summary = response.json()["summary"][0]
    assert Decimal(summary["payroll"]) == Decimal("13.50")
    assert Decimal(summary["profit"]) == Decimal("31.50")
    after, proof = earning(db_session, case)
    assert (after.id, after.amount_snapshot, proof.price_list_id) == evidence


@pytest.mark.parametrize("scope", ["PROJECT", "ORDER_NUMBER"])
def test_manual_urgency_stays_historical_after_cutover(case, client_admin_real_uow, db_session, scope):
    path = f"/api/v1/admin/projects/{case.project}/urgency-surcharges"
    payload = {"scope": scope, "order_number": "QA-1", "reason": "Historical agreement",
        "client_amount": "50", "installer_amount": "20"}
    old = client_admin_real_uow.post(path, json=payload)
    assert old.status_code == 200, old.text
    activate(case)
    rejected = client_admin_real_uow.post(path, json=payload)
    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["error"]["meta"]["reason"] == "FACTORY_URGENCY_REQUIRES_ADDON"
    assert client_admin_real_uow.get(path).json() == old.json()
    assert db_session.query(ProjectUrgencySurchargeORM).filter_by(company_id=case.company).count() == 1


def test_batch_is_atomic_when_later_item_attempts_price_override(case, client_admin_real_uow, db_session):
    activate(case)
    item = {"addon_type_id": str(case.addon), "qty_planned": "17", "client_price": "40"}
    response = client_admin_real_uow.put(f"/api/v1/admin/projects/{case.project}/addons/plan",
        json={"items": [item, {**item, "installer_price": "900"}]})
    assert response.status_code == 409, response.text
    db_session.expire_all()
    assert db_session.get(ProjectAddonPlanORM, case.plan).qty_planned == Decimal("3")


@pytest.mark.parametrize("channel", ["single", "batch", "legacy"])
def test_plan_rejects_unowned_type(case, client_admin_real_uow, channel):
    activate(case)
    response = plan_request(client_admin_real_uow, case, channel, addon_id=uuid4())
    assert response.status_code == 404, response.text


def test_installer_cannot_write_plan_price(case):
    response = plan_request(case.client, case, "single", price="999", include_price=True)
    assert response.status_code == 403, response.text


@pytest.mark.parametrize("operation", ["plan", "catalog", "urgency"])
def test_addon_writers_wait_for_activation(case, monkeypatch, db_session, operation):
    version = confirmed(case.company, case.actor, case.items)
    waiting = Event()
    lock = FactoryPriceListsRepository.lock_company
    def observed(repo, company_id):
        if current_thread() is not main_thread():
            waiting.set()
        return lock(repo, company_id)
    monkeypatch.setattr(FactoryPriceListsRepository, "lock_company", observed)
    def write():
        with pytest.raises(Conflict):
            with SqlAlchemyUnitOfWork() as uow:
                uow.session.execute(text("SET LOCAL lock_timeout = '15s'"))
                if operation == "plan":
                    AddonsUseCases.admin_set_project_plan(uow, company_id=case.company, project_id=case.project,
                        addon_type_id=case.addon, qty_planned=Decimal("50"), client_price=Decimal("40"), installer_price=Decimal("900"))
                elif operation == "catalog":
                    AddonsUseCases.admin_create_addon_type(uow, company_id=case.company, name="Forbidden default",
                        unit="pcs", default_client_price=Decimal("40"), default_installer_price=Decimal("900"))
                else:
                    AddonsUseCases.admin_create_urgency_surcharge(uow, company_id=case.company, project_id=case.project,
                        scope="PROJECT", order_number=None, reason="Forbidden manual rate", client_amount=Decimal("40"),
                        installer_amount=Decimal("20"), effective_date=None, notes=None)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with SqlAlchemyUnitOfWork() as uow:
            FactoryPriceTimelineService.activate(uow, company_id=case.company, actor_user_id=case.actor,
                price_list_id=version.id, body=ActivatePriceVersion(request_id=uuid4(),
                    expected_active_price_list_id=None, reason="Reviewed QA cutover", reviewed_transition=True))
            future = pool.submit(write)
            assert waiting.wait(timeout=10)
        future.result(timeout=20)
    db_session.expire_all()
    assert db_session.get(ProjectAddonPlanORM, case.plan).installer_price == Decimal("999")
    assert db_session.query(ProjectUrgencySurchargeORM).filter_by(company_id=case.company).count() == 0
    assert db_session.query(AddonTypeORM).filter_by(company_id=case.company, name="Forbidden default").count() == 0


def test_damaged_approval_does_not_allow_legacy_fallback_or_partial_update(case, client_admin_real_uow, db_session):
    version, _ = activate(case)
    receipt = db_session.query(FactoryPriceApprovalORM).filter_by(price_list_id=version.id).one()
    receipt.snapshot_hash = "0" * 64
    db_session.commit()
    assert plan_request(client_admin_real_uow, case, "single").status_code == 409
    assert plan_request(client_admin_real_uow, case, "single", price="900", include_price=True).status_code == 409
    assert client_admin_real_uow.get("/api/v1/admin/addons/types").status_code == 409
    db_session.expire_all()
    assert db_session.get(ProjectAddonPlanORM, case.plan).qty_planned == Decimal("3")


def test_summary_keeps_earnings_without_a_plan(case, client_admin_real_uow, db_session):
    activate(case)
    assert submit(case, "ADDON", "direct").status_code == 200
    response = client_admin_real_uow.delete(f"/api/v1/admin/projects/{case.project}/addons/plan/{case.addon}")
    assert response.status_code == 200, response.text
    response = client_admin_real_uow.get(f"/api/v1/admin/projects/{case.project}/addons")
    assert response.status_code == 200, response.text
    assert response.json()["plan"] == []
    assert Decimal(response.json()["summary"][0]["payroll"]) == Decimal("13.50")
    assert response.json()["summary"][0]["missing_plan"] is True
