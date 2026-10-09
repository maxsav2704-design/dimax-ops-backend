import csv
import io
from decimal import Decimal

import pytest

from app.modules.addons.infrastructure.models import AddonTypeORM, ProjectAddonFactORM, ProjectAddonPlanORM
from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.earnings.infrastructure.models import CompletedWorkORM
from app.modules.identity.infrastructure.models import CompanyORM
from app.modules.issues.infrastructure.models import IssueORM
from app.modules.projects.infrastructure.models import ProjectORM
from app.modules.rates.infrastructure.approval_models import FactoryPriceApprovalORM
from app.modules.reports.infrastructure.repositories import ReportsRepository
from app.shared.infrastructure.db.base import utcnow
from test_factory_earnings import case, confirmed, submit
from test_factory_installer_details import activate


def impact(client, **params):
    response = client.get("/api/v1/admin/reports/issues-addons-impact", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def mark_delayed(session, case, *, blocked=True):
    door = session.get(DoorORM, case.door)
    door.status = DoorStatus.NOT_INSTALLED
    session.add(IssueORM(company_id=case.company, door_id=case.door, title="QA access",
                         workflow_state="BLOCKED" if blocked else "NEW"))
    session.commit()


@pytest.mark.parametrize("factory", [False, True])
def test_forecast_uses_active_price_and_deduplicates_issue_delay_overlap(case, client_admin_real_uow, db_session, factory):
    if factory:
        version, _ = activate(case)
    else:
        confirmed(case.company, case.actor, case.items)
    mark_delayed(db_session, case)
    data = impact(client_admin_real_uow)
    summary = data["summary"]
    assert summary["pricing_mode"] == ("FACTORY" if factory else "LEGACY")
    assert summary["open_issues"] == summary["blocked_open_issues"] == summary["not_installed_doors"] == summary["exposure_doors"] == 1
    expected = Decimal("250" if factory else "-499")
    for key in ("open_issue_profit_at_risk", "blocked_issue_profit_at_risk", "delayed_profit_total", "exposure_profit_total"):
        assert Decimal(summary[key]) == expected
    assert summary["price_list_version"] == (1 if factory else None)
    if factory:
        activate(case, expected=1, previous=version.id, door_price="300")
        assert Decimal(impact(client_admin_real_uow)["summary"]["exposure_profit_total"]) == 200
    assert db_session.query(CompletedWorkORM).filter_by(company_id=case.company).count() == 0


def test_missing_price_invalidates_only_affected_totals_and_preserves_coverage_before_limit(
    case, client_admin_real_uow, db_session, make_door_type, make_reason,
):
    activate(case)
    mark_delayed(db_session, case)
    reason = make_reason(name="A priced")
    db_session.get(DoorORM, case.door).reason_id = reason.id
    missing = DoorORM(company_id=case.company, project_id=case.project, door_type_id=make_door_type().id,
        unit_label="QA missing rate", status=DoorStatus.NOT_INSTALLED, our_price=700, installer_rate_snapshot=999,
        reason_id=make_reason(name="B unpriced").id, version=0, is_locked=False)
    db_session.add(missing)
    db_session.flush()
    db_session.add(IssueORM(company_id=case.company, door_id=missing.id, title="Unpriced issue", workflow_state="NEW"))
    db_session.commit()
    data = impact(client_admin_real_uow, limit=1)
    summary = data["summary"]
    assert summary["open_issue_payroll_at_risk"] is summary["open_issue_profit_at_risk"] is None
    assert summary["delayed_payroll_total"] is summary["delayed_profit_total"] is summary["exposure_profit_total"] is None
    assert Decimal(summary["blocked_issue_profit_at_risk"]) == 250
    assert summary["unpriced_blocked_issue_doors"] == 0
    assert summary["unpriced_open_issue_doors"] == summary["unpriced_delayed_doors"] == summary["unpriced_exposure_doors"] == 1
    assert summary["reason_rows_total"] == summary["exposure_doors"] == 2
    assert data["top_reasons"][0]["reason_name"] == "A priced"
    assert impact(client_admin_real_uow)["top_reasons"][-1]["profit_delayed_total"] is None
    risk = client_admin_real_uow.get("/api/v1/admin/reports/risk-concentration")
    assert risk.status_code == 200, risk.text
    assert risk.json()["summary"]["open_issue_profit_at_risk"] is None
    assert risk.json()["summary"]["exposure_profit_total"] is None
    assert risk.json()["summary"]["unpriced_exposure_doors"] == 1
    response = client_admin_real_uow.get("/api/v1/admin/reports/executive/export")
    assert response.status_code == 200, response.text
    exported = {row["section"]: row for row in csv.DictReader(io.StringIO(response.text))}
    assert exported["margin_leakage"]["value_1"] == ""
    assert exported["issue_exposure_total"]["value_1"] == "2"
    assert exported["issue_exposure_total"]["value_2"] == ""
    assert exported["issue_exposure_total"]["value_3"] == "1"
    assert exported["issue_exposure_basis"]["metric"] == "FACTORY"


@pytest.mark.parametrize("change", ["price", "missing_plan", "reversal", "correction", "unrecorded"])
def test_addon_actuals_use_shared_ledger_projection(case, client_admin_real_uow, db_session, change):
    if change == "correction":
        assert submit(case, "ADDON", "direct").status_code == 200
        work = db_session.query(CompletedWorkORM).filter_by(company_id=case.company).one()
        response = client_admin_real_uow.post("/api/v1/admin/earnings/corrections", json={
            "completed_work_id": str(work.id), "rate_snapshot": "8", "reason": "QA agreed correction"})
        assert response.status_code == 201, response.text
    version, _ = activate(case)
    if change == "unrecorded":
        db_session.add(ProjectAddonFactORM(company_id=case.company, project_id=case.project,
            addon_type_id=case.addon, installer_id=case.installer, qty_done=2, done_at=utcnow()))
    elif change != "correction":
        assert submit(case, "ADDON", "direct").status_code == 200
    if change == "missing_plan":
        db_session.delete(db_session.get(ProjectAddonPlanORM, case.plan))
    elif change == "price":
        plan = db_session.get(ProjectAddonPlanORM, case.plan)
        plan.installer_price, plan.client_price = 777, 30
    elif change == "reversal":
        work = db_session.query(CompletedWorkORM).filter_by(company_id=case.company).one()
        db_session.add(CompletedWorkORM(company_id=case.company, project_id=case.project,
            installer_id=case.installer, work_kind="ADDON", addon_fact_id=work.addon_fact_id,
            quantity=work.quantity, rate_snapshot=-work.rate_snapshot, amount_snapshot=-work.amount_snapshot,
            completed_at=utcnow(), entry_type="REVERSAL", correction_ref_id=work.id))
    db_session.commit()
    if change == "price":
        activate(case, expected=1, previous=version.id, addon_price="12")
    before = list(db_session.query(CompletedWorkORM.id, CompletedWorkORM.amount_snapshot).filter_by(company_id=case.company).order_by(CompletedWorkORM.id))
    data = impact(client_admin_real_uow)
    summary = data["summary"]
    expected_payroll = Decimal("0" if change in ("unrecorded", "reversal") else "12" if change == "correction" else "13.50")
    assert Decimal(summary["addon_payroll_total"]) == expected_payroll
    assert (summary["addon_profit_total"] is None) == (change in ("unrecorded", "missing_plan"))
    assert summary["addon_unrecorded_completed_works"] == int(change == "unrecorded")
    assert summary["addon_missing_client_prices"] == int(change == "missing_plan")
    assert summary["incomplete_addon_rows"] == int(change in ("unrecorded", "missing_plan"))
    if change == "reversal":
        assert data["addon_impact"] == [] and summary["addon_rows_total"] == 0
    else:
        row = data["addon_impact"][0]
        assert Decimal(row["qty_done"]) == (0 if change == "unrecorded" else Decimal("1.50"))
        assert Decimal(row["payroll_total"]) == expected_payroll
        if change == "price":
            assert Decimal(row["revenue_total"]) == 45 and Decimal(row["profit_total"]) == Decimal("31.50")
    assert before == list(db_session.query(CompletedWorkORM.id, CompletedWorkORM.amount_snapshot).filter_by(company_id=case.company).order_by(CompletedWorkORM.id))


def test_addon_coverage_counts_unshown_types_and_keeps_unknown_profit_last(case, client_admin_real_uow, db_session):
    activate(case)
    assert submit(case, "ADDON", "direct").status_code == 200
    extra = AddonTypeORM(company_id=case.company, name="Unrecorded adjustment", unit="pcs", is_active=True)
    db_session.add(extra)
    db_session.flush()
    db_session.add(ProjectAddonFactORM(company_id=case.company, project_id=case.project,
        addon_type_id=extra.id, installer_id=case.installer, qty_done=2, done_at=utcnow()))
    db_session.commit()
    data = impact(client_admin_real_uow, limit=1)
    assert data["summary"]["addon_rows_total"] == 2
    assert data["summary"]["incomplete_addon_rows"] == data["summary"]["addon_unrecorded_completed_works"] == 1
    assert data["summary"]["addon_profit_total"] is None
    assert len(data["addon_impact"]) == 1 and data["addon_impact"][0]["addon_type_id"] == str(case.addon)
    assert impact(client_admin_real_uow)["addon_impact"][-1]["profit_total"] is None


def test_foreign_addon_metadata_is_unavailable_but_does_not_discard_recorded_money(case, client_admin_real_uow, db_session):
    activate(case)
    assert submit(case, "ADDON", "direct").status_code == 200
    foreign = CompanyORM(name="Private addon tenant")
    db_session.add(foreign)
    db_session.flush()
    addon = AddonTypeORM(company_id=foreign.id, name="Private addon name", unit="pcs", is_active=True)
    db_session.add(addon)
    db_session.flush()
    fact = db_session.query(ProjectAddonFactORM).filter_by(company_id=case.company).one()
    fact.addon_type_id = addon.id
    db_session.commit()
    try:
        data = impact(client_admin_real_uow)
        row = data["addon_impact"][0]
        assert row["addon_type_id"] is None and row["addon_name"] == "Unknown add-on"
        assert Decimal(row["payroll_total"]) == Decimal("13.50")
        assert row["profit_total"] is None and row["missing_client_prices"] == 1
        assert "Private" not in str(data) and str(addon.id) not in str(data)
    finally:
        fact.addon_type_id = case.addon
        db_session.flush()
        db_session.delete(addon)
        db_session.flush()
        db_session.delete(foreign)
        db_session.commit()


def test_executive_reuses_one_exposure_calculation(case, client_admin_real_uow, db_session, monkeypatch):
    activate(case)
    mark_delayed(db_session, case)
    original = ReportsRepository.issues_addons_impact
    calls = []

    def tracked(repository, **kwargs):
        calls.append(kwargs)
        return original(repository, **kwargs)

    monkeypatch.setattr(ReportsRepository, "issues_addons_impact", tracked)
    response = client_admin_real_uow.get("/api/v1/admin/reports/executive/export")
    assert response.status_code == 200, response.text
    assert len(calls) == 1
    rows = list(csv.DictReader(io.StringIO(response.text)))
    summary = next(row for row in rows if row["section"] == "executive_summary" and row["metric"] == "risk_concentration")
    leakage = next(row for row in rows if row["section"] == "margin_leakage")
    assert Decimal(summary["value_1"]) == Decimal(leakage["value_1"]) == 250
    basis = next(row for row in rows if row["section"] == "issue_exposure_basis")
    assert basis["metric"] == "FACTORY" and basis["value_3"] == "1"


def test_empty_scope_keeps_confirmed_basis_and_zero_forecast(case, client_admin_real_uow):
    activate(case)
    data = impact(client_admin_real_uow)
    assert data["summary"]["pricing_mode"] == "FACTORY"
    assert Decimal(data["summary"]["exposure_profit_total"]) == 0
    assert data["summary"]["reason_rows_total"] == data["summary"]["addon_rows_total"] == 0
    assert data["top_reasons"] == data["addon_impact"] == []


@pytest.mark.parametrize("factory", [False, True])
def test_cross_company_issue_links_cannot_expose_foreign_door_values(case, client_admin_real_uow, db_session, factory):
    if factory:
        activate(case)
    foreign = CompanyORM(name="Private exposure tenant")
    db_session.add(foreign)
    db_session.flush()
    project = ProjectORM(company_id=foreign.id, name="Private exposure site", address="QA", status="OK")
    db_session.add(project)
    db_session.flush()
    door = DoorORM(company_id=foreign.id, project_id=project.id, door_type_id=case.door_type,
        unit_label="Private position", status=DoorStatus.NOT_INSTALLED, our_price=9000, version=0, is_locked=False)
    db_session.add(door)
    db_session.flush()
    local_issue = IssueORM(company_id=case.company, door_id=door.id, title="Corrupt local link")
    foreign_issue = IssueORM(company_id=foreign.id, door_id=case.door, title="Private problem")
    db_session.add_all([local_issue, foreign_issue])
    db_session.commit()
    try:
        data = impact(client_admin_real_uow)
        assert data["summary"]["open_issues"] == data["summary"]["exposure_doors"] == 0
        assert Decimal(data["summary"]["open_issue_revenue_at_risk"]) == 0
        assert "Private" not in str(data) and "9000" not in str(data)
    finally:
        for entity in (local_issue, foreign_issue, door, project, foreign):
            db_session.delete(entity)
            db_session.flush()
        db_session.commit()


@pytest.mark.parametrize("path", ["issues-addons-impact", "risk-concentration", "executive/export"])
def test_roles_and_invalid_factory_receipt_fail_closed(case, client_admin_real_uow, db_session, path):
    version, _ = activate(case)
    url = f"/api/v1/admin/reports/{path}"
    assert case.client.get(url).status_code == 403
    db_session.query(FactoryPriceApprovalORM).filter_by(price_list_id=version.id).one().snapshot_hash = "0" * 64
    db_session.commit()
    assert client_admin_real_uow.get(url).status_code == 409
