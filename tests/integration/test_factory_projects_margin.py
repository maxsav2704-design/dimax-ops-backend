import csv
import io
from decimal import Decimal

import pytest

from app.modules.addons.infrastructure.models import ProjectAddonFactORM, ProjectAddonPlanORM
from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.earnings.infrastructure.models import CompletedWorkORM
from app.modules.identity.infrastructure.models import CompanyORM
from app.modules.projects.infrastructure.models import ProjectORM
from app.modules.rates.infrastructure.approval_models import FactoryPriceApprovalORM
from app.shared.infrastructure.db.base import utcnow
from test_factory_earnings import case, activate, confirmed, submit


def margins(client, query=""):
    response = client.get(f"/api/v1/admin/reports/projects-margin?{query}")
    assert response.status_code == 200, response.text
    return response.json()


def project_row(client, project_id):
    return next(item for item in margins(client)["items"] if item["project_id"] == str(project_id))


def test_confirmed_but_inactive_keeps_legacy_report(case, client_admin_real_uow, db_session):
    door = db_session.get(DoorORM, case.door)
    door.status, door.installed_at = DoorStatus.INSTALLED, utcnow()
    db_session.commit()
    confirmed(case.company, case.actor, case.items)
    result = margins(client_admin_real_uow)
    assert result["pricing_mode"] == "LEGACY"
    assert result["incomplete_projects"] == 0
    assert Decimal(result["items"][0]["payroll_total"]) == Decimal("999")


def test_recorded_totals_match_plan_fact_after_price_change(case, client_admin_real_uow, db_session):
    v1, _ = activate(case)
    assert submit(case, "DOOR", "install").status_code == 200
    assert submit(case, "ADDON", "direct").status_code == 200
    assert submit(case, "ADDON", "direct").status_code == 200
    before = list(db_session.query(CompletedWorkORM.id, CompletedWorkORM.amount_snapshot)
                  .filter_by(company_id=case.company).order_by(CompletedWorkORM.id))
    activate(case, expected=1, previous=v1.id, door_price="300", addon_price="12")
    item = project_row(client_admin_real_uow, case.project)
    assert item["pricing_mode"] == "FACTORY"
    assert Decimal(item["revenue_total"]) == Decimal("560")
    assert Decimal(item["payroll_total"]) == Decimal("277")
    assert Decimal(item["profit_total"]) == Decimal("283")
    result = client_admin_real_uow.get(f"/api/v1/admin/reports/project-plan-fact/{case.project}")
    assert result.status_code == 200, result.text
    for field in ("payroll", "revenue", "profit"):
        assert Decimal(item[f"{field}_total"]) == Decimal(result.json()[f"actual_{field}_total"])
    assert before == list(db_session.query(CompletedWorkORM.id, CompletedWorkORM.amount_snapshot)
                          .filter_by(company_id=case.company).order_by(CompletedWorkORM.id))


def test_cancellation_and_reassignment_cannot_reprice_project(case, client_admin_real_uow, db_session, make_reason):
    activate(case)
    assert submit(case, "DOOR", "install").status_code == 200
    assert submit(case, "ADDON", "direct").status_code == 200
    response = client_admin_real_uow.post(f"/api/v1/admin/doors/{case.door}/override", json={
        "new_status": "NOT_INSTALLED", "reason_id": str(make_reason().id), "override_reason": "QA cancel"})
    assert response.status_code == 200, response.text
    door = db_session.get(DoorORM, case.door)
    door.installer_id, door.installer_rate_snapshot = None, Decimal("1234")
    db_session.commit()
    item = project_row(client_admin_real_uow, case.project)
    assert item["installed_doors"] == 0
    assert Decimal(item["payroll_total"]) == Decimal("13.50")
    assert Decimal(item["profit_total"]) == Decimal("16.50")


@pytest.mark.parametrize("kind,channel,rate,expected", [
    ("DOOR", "install", "280", "280"), ("ADDON", "direct", "8", "12"),
])
def test_legacy_corrections_survive_activation(case, client_admin_real_uow, db_session, kind, channel, rate, expected):
    assert submit(case, kind, channel).status_code == 200
    work = db_session.query(CompletedWorkORM).filter_by(company_id=case.company).one()
    response = client_admin_real_uow.post("/api/v1/admin/earnings/corrections", json={
        "completed_work_id": str(work.id), "rate_snapshot": rate, "reason": "QA legacy correction"})
    assert response.status_code == 201, response.text
    activate(case)
    assert Decimal(project_row(client_admin_real_uow, case.project)["payroll_total"]) == Decimal(expected)


@pytest.mark.parametrize("kind", ["DOOR", "ADDON"])
def test_unrecorded_work_has_no_invented_profit(case, client_admin_real_uow, db_session, kind):
    activate(case)
    if kind == "DOOR":
        door = db_session.get(DoorORM, case.door)
        door.status, door.installed_at = DoorStatus.INSTALLED, utcnow()
    else:
        db_session.add(ProjectAddonFactORM(company_id=case.company, project_id=case.project,
            addon_type_id=case.addon, installer_id=case.installer, qty_done=Decimal("2"), done_at=utcnow()))
    db_session.commit()
    result = margins(client_admin_real_uow)
    assert result["incomplete_projects"] == 1
    item = result["items"][0]
    assert item["unrecorded_completed_works"] == 1
    assert Decimal(item["payroll_total"]) == 0
    assert item["profit_total"] is None and item["margin_pct"] is None
    response = client_admin_real_uow.get("/api/v1/admin/reports/risk-concentration")
    assert response.status_code == 200, response.text
    assert response.json()["summary"]["worst_project_profit_total"] is None
    assert response.json()["summary"]["incomplete_projects"] == 1
    assert response.json()["projects"][0]["unrecorded_completed_works"] == 1


def test_deleted_addon_plan_preserves_earnings_not_margin(case, client_admin_real_uow, db_session):
    activate(case)
    assert submit(case, "ADDON", "direct").status_code == 200
    db_session.delete(db_session.get(ProjectAddonPlanORM, case.plan))
    db_session.commit()
    item = project_row(client_admin_real_uow, case.project)
    assert Decimal(item["payroll_total"]) == Decimal("13.50")
    assert item["profit_total"] is None and item["margin_pct"] is None
    assert item["missing_addon_plans_facts"] == 1
    assert item["unrecorded_completed_works"] == 0


@pytest.mark.parametrize("sort_dir", ["asc", "desc"])
def test_unknown_profit_is_not_ranked_as_zero_and_coverage_is_unpaginated(case, client_admin_real_uow, db_session, sort_dir):
    activate(case)
    door = db_session.get(DoorORM, case.door)
    door.status, door.installed_at = DoorStatus.INSTALLED, utcnow()
    for index in range(2):
        db_session.add(ProjectORM(company_id=case.company, name="Same empty site", address=f"QA {index}", status="OK"))
    db_session.commit()
    pages = [margins(client_admin_real_uow, f"limit=1&offset={offset}&sort_dir={sort_dir}") for offset in range(3)]
    assert all(page["total"] == 3 and page["incomplete_projects"] == 1 for page in pages)
    ids = [page["items"][0]["project_id"] for page in pages]
    assert len(set(ids)) == 3
    assert ids[0] < ids[1]
    assert ids[2] == str(case.project)
    assert Decimal(pages[0]["items"][0]["payroll_total"]) == 0
    assert margins(client_admin_real_uow, f"limit=1&sort_dir={sort_dir}")["items"][0]["project_id"] == ids[0]


@pytest.mark.parametrize("missing", [False, True])
def test_csv_and_risk_project_rows_match_api(case, client_admin_real_uow, db_session, missing):
    activate(case)
    assert submit(case, "DOOR", "install").status_code == 200
    assert submit(case, "ADDON", "direct").status_code == 200
    if missing:
        db_session.delete(db_session.get(ProjectAddonPlanORM, case.plan))
        db_session.commit()
    item = project_row(client_admin_real_uow, case.project)
    risk = client_admin_real_uow.get("/api/v1/admin/reports/risk-concentration")
    assert risk.status_code == 200, risk.text
    assert risk.json()["projects"][0] == item
    response = client_admin_real_uow.get("/api/v1/admin/reports/executive/export")
    assert response.status_code == 200, response.text
    rows = {row["section"]: row for row in csv.DictReader(io.StringIO(response.text))}
    for section in ("top_projects", "risk_projects"):
        if missing:
            assert rows[section]["value_1"] == "" and rows[section]["value_2"] == ""
        else:
            assert Decimal(rows[section]["value_1"]) == Decimal(item["profit_total"])
        assert rows[f"{section}_coverage"]["value_1"] == str(case.project)
        assert rows[f"{section}_coverage"]["value_2"] == "FACTORY"
        assert rows[f"{section}_coverage"]["value_4"] == str(int(missing))
    assert rows["projects_margin_basis"]["value_1"] == "ledger_actuals"
    assert rows["projects_margin_basis"]["value_2"] == str(int(missing))


def test_foreign_and_deleted_projects_are_excluded(case, client_admin_real_uow, db_session):
    activate(case)
    assert submit(case, "DOOR", "install").status_code == 200
    company = CompanyORM(name="Private report tenant")
    db_session.add(company)
    db_session.flush()
    foreign = ProjectORM(company_id=company.id, name="Private site", address="QA", status="OK")
    deleted = ProjectORM(company_id=case.company, name="Deleted site", address="QA", status="OK", deleted_at=utcnow())
    db_session.add_all([foreign, deleted])
    db_session.commit()
    try:
        result = margins(client_admin_real_uow)
        assert result["total"] == 1
        assert [item["project_id"] for item in result["items"]] == [str(case.project)]
        assert Decimal(result["items"][0]["payroll_total"]) == Decimal("250")
    finally:
        db_session.delete(foreign)
        db_session.delete(company)
        db_session.commit()


@pytest.mark.parametrize("path", ["projects-margin", "risk-concentration", "executive/export"])
def test_scope_and_corrupt_confirmation_fail_closed(case, client_admin_real_uow, db_session, path):
    version, _ = activate(case)
    url = f"/api/v1/admin/reports/{path}"
    assert case.client.get(url).status_code == 403
    receipt = db_session.query(FactoryPriceApprovalORM).filter_by(price_list_id=version.id).one()
    receipt.snapshot_hash = "0" * 64
    db_session.commit()
    assert client_admin_real_uow.get(url).status_code == 409
