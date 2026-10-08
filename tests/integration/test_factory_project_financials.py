import csv
import io
from decimal import Decimal

import pytest

from app.modules.addons.infrastructure.models import AddonTypeORM, ProjectAddonFactORM, ProjectAddonPlanORM
from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.earnings.infrastructure.models import CompletedWorkORM
from app.modules.identity.infrastructure.models import CompanyORM
from app.modules.projects.infrastructure.models import ProjectORM
from app.modules.rates.infrastructure.approval_models import FactoryPriceApprovalORM
from app.shared.infrastructure.db.base import utcnow
from test_factory_earnings import case, activate, confirmed, submit


def report(client, case, kind="project-plan-fact"):
    response = client.get(f"/api/v1/admin/reports/{kind}/{case.project}")
    assert response.status_code == 200, response.text
    return response.json()


def test_plan_uses_effective_not_merely_confirmed_version(case, client_admin_real_uow):
    client = client_admin_real_uow
    confirmed(case.company, case.actor, case.items)
    legacy = report(client, case)
    assert legacy["pricing_mode"] == "LEGACY"
    assert Decimal(legacy["planned_payroll_total"]) == Decimal("3996")
    version, _ = activate(case, expected=1)
    confirmed(case.company, case.actor, [{**item, "installer_price": "400"} for item in case.items], 2)
    result = report(client, case)
    assert result["pricing_mode"] == "FACTORY"
    assert result["price_list_id"] == str(version.id)
    assert result["price_list_version"] == 2
    assert Decimal(result["planned_payroll_total"]) == Decimal("277")
    assert Decimal(result["actual_payroll_total"]) == 0
    assert Decimal(result["planned_profit_total"]) == Decimal("283")


def test_price_change_never_reprices_earnings_or_order_profit(case, client_admin_real_uow, db_session):
    db_session.get(DoorORM, case.door).order_number = "QA-ORDER"
    db_session.commit()
    v1, _ = activate(case)
    assert submit(case, "DOOR", "install").status_code == 200
    assert submit(case, "ADDON", "direct").status_code == 200
    evidence = list(db_session.query(CompletedWorkORM.id, CompletedWorkORM.amount_snapshot)
                    .filter_by(company_id=case.company).order_by(CompletedWorkORM.id))
    activate(case, expected=1, previous=v1.id, door_price="300", addon_price="12")
    result = report(client_admin_real_uow, case)
    assert Decimal(result["planned_payroll_total"]) == Decimal("336")
    assert Decimal(result["actual_payroll_total"]) == Decimal("263.50")
    assert Decimal(result["payroll_gap_total"]) == Decimal("72.50")
    risk = report(client_admin_real_uow, case, "project-risk-drilldown")
    assert Decimal(risk["summary"]["actual_profit_total"]) == Decimal("266.50")
    assert Decimal(risk["summary"]["addon_profit_total"]) == Decimal("16.50")
    assert Decimal(risk["risky_orders"][0]["actual_profit_total"]) == Decimal("250")
    assert evidence == list(db_session.query(CompletedWorkORM.id, CompletedWorkORM.amount_snapshot)
                           .filter_by(company_id=case.company).order_by(CompletedWorkORM.id))


def add_unpriced(case, db_session, make_door_type, kind, qty="3"):
    if kind == "DOOR":
        door = db_session.get(DoorORM, case.door)
        door.door_type_id = make_door_type(name="Unpriced new door").id
        door.status = DoorStatus.NOT_INSTALLED
    else:
        addon = AddonTypeORM(company_id=case.company, name="Unpriced new work", unit="pcs")
        db_session.add(addon)
        db_session.flush()
        plan = db_session.get(ProjectAddonPlanORM, case.plan)
        plan.addon_type_id = addon.id
        plan.qty_planned = Decimal(qty)
    db_session.commit()


@pytest.mark.parametrize("kind", ["DOOR", "ADDON"])
def test_unpriced_work_invalidates_plan_not_recorded_payroll(case, client_admin_real_uow, db_session, make_door_type, kind):
    activate(case)
    add_unpriced(case, db_session, make_door_type, kind)
    result = report(client_admin_real_uow, case)
    for field in ("planned_payroll_total", "planned_profit_total", "payroll_gap_total", "profit_gap_total"):
        assert result[field] is None
    assert result[f"missing_planned_rates_{'doors' if kind == 'DOOR' else 'addons'}"] == 1
    assert Decimal(result["actual_payroll_total"]) == 0
    risk = report(client_admin_real_uow, case, "project-risk-drilldown")
    assert risk["summary"]["planned_profit_total"] is None
    if kind == "DOOR":
        assert risk["summary"]["delayed_profit_total"] is None
        assert risk["top_reasons"][0]["profit_delayed_total"] is None


def test_zero_quantity_does_not_require_a_price(case, client_admin_real_uow, db_session, make_door_type):
    activate(case)
    add_unpriced(case, db_session, make_door_type, "ADDON", qty="0")
    result = report(client_admin_real_uow, case)
    assert result["missing_planned_rates_addons"] == 0
    assert Decimal(result["planned_payroll_total"]) == Decimal("250")


@pytest.mark.parametrize("kind", ["DOOR", "ADDON"])
def test_unrecorded_work_is_not_turned_into_earnings(case, client_admin_real_uow, db_session, kind):
    activate(case)
    if kind == "DOOR":
        door = db_session.get(DoorORM, case.door)
        door.status, door.installed_at, door.order_number = DoorStatus.INSTALLED, utcnow(), "UNRECORDED"
    else:
        db_session.add(ProjectAddonFactORM(company_id=case.company, project_id=case.project,
            addon_type_id=case.addon, installer_id=case.installer, qty_done=Decimal("2"), done_at=utcnow()))
    db_session.commit()
    result = report(client_admin_real_uow, case)
    assert result["unrecorded_completed_works"] == 1
    assert Decimal(result["actual_payroll_total"]) == 0
    assert result["actual_profit_total"] is None
    assert result["profit_gap_total"] is None
    risk = report(client_admin_real_uow, case, "project-risk-drilldown")
    assert risk["summary"]["actual_margin_pct"] is None
    if kind == "DOOR":
        assert risk["risky_orders"][0]["actual_profit_total"] is None
    assert db_session.query(CompletedWorkORM).filter_by(company_id=case.company).count() == 0


def test_cancellation_does_not_restore_addon_plan_price(case, client_admin_real_uow, db_session, make_reason):
    activate(case)
    assert submit(case, "DOOR", "install").status_code == 200
    assert submit(case, "ADDON", "direct").status_code == 200
    response = client_admin_real_uow.post(f"/api/v1/admin/doors/{case.door}/override", json={
        "new_status": "NOT_INSTALLED", "reason_id": str(make_reason().id), "override_reason": "QA cancellation"})
    assert response.status_code == 200, response.text
    result = report(client_admin_real_uow, case)
    assert Decimal(result["actual_payroll_total"]) == Decimal("13.50")
    assert Decimal(result["actual_profit_total"]) == Decimal("16.50")


def test_legacy_correction_is_preserved_after_activation(case, client_admin_real_uow, db_session):
    assert submit(case, "DOOR", "install").status_code == 200
    work = db_session.query(CompletedWorkORM).filter_by(company_id=case.company).one()
    response = client_admin_real_uow.post("/api/v1/admin/earnings/corrections", json={
        "completed_work_id": str(work.id), "rate_snapshot": "280", "reason": "QA legacy correction"})
    assert response.status_code == 201, response.text
    activate(case)
    assert Decimal(report(client_admin_real_uow, case)["actual_payroll_total"]) == Decimal("280")


def test_deleted_plan_keeps_payroll_but_not_invented_margin(case, client_admin_real_uow, db_session):
    activate(case)
    assert submit(case, "ADDON", "direct").status_code == 200
    db_session.delete(db_session.get(ProjectAddonPlanORM, case.plan))
    db_session.commit()
    result = report(client_admin_real_uow, case)
    assert Decimal(result["actual_payroll_total"]) == Decimal("13.50")
    assert result["missing_addon_plans_facts"] == 1
    assert result["actual_profit_total"] is None


def test_historical_urgency_is_not_confirmed_payroll(case, client_admin_real_uow):
    response = client_admin_real_uow.post(f"/api/v1/admin/projects/{case.project}/urgency-surcharges", json={
        "scope": "PROJECT", "reason": "QA historical agreement", "client_amount": "100", "installer_amount": "80"})
    assert response.status_code == 200, response.text
    activate(case)
    result = report(client_admin_real_uow, case)
    assert Decimal(result["urgency_installer_total"]) == Decimal("80")
    assert Decimal(result["planned_payroll_total"]) == Decimal("277")
    assert Decimal(result["actual_payroll_total"]) == 0


def test_empty_project_does_not_include_another_projects_earnings(case, client_admin_real_uow, db_session):
    activate(case)
    assert submit(case, "DOOR", "install").status_code == 200
    assert submit(case, "ADDON", "direct").status_code == 200
    empty = ProjectORM(company_id=case.company, name="Empty site", address="QA", status="OK")
    db_session.add(empty)
    db_session.commit()
    case.project = empty.id
    result = report(client_admin_real_uow, case)
    assert result["total_doors"] == 0
    assert Decimal(result["planned_payroll_total"]) == 0
    assert Decimal(result["actual_payroll_total"]) == 0
    assert Decimal(result["planned_profit_total"]) == 0


def test_active_list_without_addon_prices_is_not_zero_rate(case, client_admin_real_uow, db_session):
    db_session.delete(db_session.get(ProjectAddonPlanORM, case.plan))
    db_session.get(AddonTypeORM, case.addon).is_active = False
    db_session.commit()
    case.items = [item for item in case.items if item["kind"] == "DOOR"]
    activate(case)
    created = client_admin_real_uow.post("/api/v1/admin/addons/types", json={"name": "Later additional work"})
    assert created.status_code == 200, created.text
    response = client_admin_real_uow.post(f"/api/v1/admin/projects/{case.project}/addons/plan", json={
        "addon_type_id": created.json()["id"], "qty_planned": "2", "client_price": "20"})
    assert response.status_code == 200, response.text
    result = report(client_admin_real_uow, case)
    assert result["planned_payroll_total"] is None
    assert result["missing_planned_rates_addons"] == 1


@pytest.mark.parametrize("missing", [False, True])
def test_csv_preserves_nullable_totals_and_price_basis(case, client_admin_real_uow, db_session, make_door_type, missing):
    version, _ = activate(case)
    if missing:
        add_unpriced(case, db_session, make_door_type, "ADDON")
    response = client_admin_real_uow.get(
        f"/api/v1/admin/reports/executive/export?project_plan_fact_project_id={case.project}"
        f"&project_risk_project_id={case.project}")
    assert response.status_code == 200, response.text
    rows = {row["section"]: row for row in csv.DictReader(io.StringIO(response.text))}
    assert rows["project_plan_fact_pricing"]["metric"] == "FACTORY"
    assert rows["project_plan_fact_pricing"]["value_1"] == str(version.id)
    assert rows["project_plan_fact_payroll"]["value_4"] == "ledger_actuals"
    assert rows["project_risk_pricing"]["value_1"] == str(version.id)
    if missing:
        assert rows["project_plan_fact_payroll"]["value_1"] == ""
        assert rows["project_plan_fact"]["value_1"] == ""
        assert rows["project_plan_fact_coverage"]["value_2"] == "1"
        assert rows["project_risk_coverage"]["value_2"] == "1"
        assert rows["project_risk_drilldown"]["value_1"] == ""
    else:
        assert Decimal(rows["project_plan_fact_payroll"]["value_1"]) == Decimal("277")


@pytest.mark.parametrize("path", ["project-plan-fact", "project-risk-drilldown", "executive/export?project_plan_fact_project_id="])
def test_financial_scope_and_bad_receipt_fail_closed(case, client_admin_real_uow, db_session, path):
    version, _ = activate(case)
    url = f"/api/v1/admin/reports/{path}{'' if '?' in path else '/'}{case.project}"
    assert case.client.get(url).status_code == 403
    company = CompanyORM(name="Other financial tenant")
    db_session.add(company)
    db_session.flush()
    other = ProjectORM(company_id=company.id, name="Private", address="QA", status="OK")
    db_session.add(other)
    db_session.commit()
    assert client_admin_real_uow.get(url.replace(str(case.project), str(other.id))).status_code == 404
    db_session.delete(other)
    db_session.delete(company)
    db_session.commit()
    receipt = db_session.query(FactoryPriceApprovalORM).filter_by(price_list_id=version.id).one()
    receipt.snapshot_hash = "0" * 64
    db_session.commit()
    assert client_admin_real_uow.get(url).status_code == 409
