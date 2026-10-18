import csv
import io
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.modules.addons.infrastructure.models import ProjectAddonFactORM, ProjectAddonPlanORM
from app.modules.doors.application.commands import MarkDoorInstalled
from app.modules.doors.application.use_cases import DoorUseCases
from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.earnings.infrastructure.models import CompletedWorkORM
from app.modules.identity.infrastructure.models import CompanyORM
from app.modules.installers.infrastructure.models import InstallerORM
from app.modules.issues.infrastructure.models import IssueORM
from app.modules.projects.infrastructure.models import ProjectORM
from app.modules.rates.infrastructure.approval_models import FactoryPriceApprovalORM
from app.shared.infrastructure.db.base import utcnow
from app.shared.infrastructure.db.uow_sqlalchemy import SqlAlchemyUnitOfWork
from test_factory_earnings import case, activate, confirmed, submit


PATHS = ("installers-profitability-matrix", "installer-project-profitability")


def matrix(client, path, query=""):
    response = client.get(f"/api/v1/admin/reports/{path}?{query}")
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("path", PATHS)
def test_inactive_confirmation_keeps_legacy(case, client_admin_real_uow, db_session, path):
    door = db_session.get(DoorORM, case.door)
    door.status, door.installed_at = DoorStatus.INSTALLED, utcnow()
    db_session.commit()
    confirmed(case.company, case.actor, case.items)
    data = matrix(client_admin_real_uow, path)
    assert data["pricing_mode"] == "LEGACY" and data["incomplete_items"] == 0
    assert Decimal(data["items"][0]["payroll_total"]) == Decimal("999")


@pytest.mark.parametrize("assignment", ["other", "none"])
def test_history_stays_with_performer_after_price_and_assignment_change(
    case, client_admin_real_uow, db_session, make_installer, assignment,
):
    version, _ = activate(case)
    assert submit(case, "DOOR", "install").status_code == 200
    assert submit(case, "ADDON", "direct").status_code == 200
    assert submit(case, "ADDON", "direct").status_code == 200
    before = list(db_session.query(CompletedWorkORM.id, CompletedWorkORM.amount_snapshot)
                  .filter_by(company_id=case.company).order_by(CompletedWorkORM.id))
    other = make_installer(full_name="New assignee")
    door = db_session.get(DoorORM, case.door)
    door.installer_id = other.id if assignment == "other" else None
    door.installer_rate_snapshot = Decimal("1234")
    installer = db_session.get(InstallerORM, case.installer)
    installer.is_active, installer.status = False, "INACTIVE"
    db_session.commit()
    activate(case, expected=1, previous=version.id, door_price="300", addon_price="12")
    for path in PATHS:
        data = matrix(client_admin_real_uow, path)
        assert data["pricing_mode"] == "FACTORY" and data["total"] == 1
        item = data["items"][0]
        assert item["installer_id"] == str(case.installer)
        assert item["installed_doors"] == 1 and Decimal(item["addons_done_qty"]) == 3
        assert Decimal(item["revenue_total"]) == 560
        assert Decimal(item["payroll_total"]) == 277
        assert Decimal(item["profit_total"]) == 283
        assert item["unrecorded_completed_works"] == 0
    assert before == list(db_session.query(CompletedWorkORM.id, CompletedWorkORM.amount_snapshot)
                          .filter_by(company_id=case.company).order_by(CompletedWorkORM.id))


def test_cancel_then_reinstall_credits_only_second_performer(case, client_admin_real_uow, db_session, make_reason, make_installer):
    activate(case)
    assert submit(case, "DOOR", "install").status_code == 200
    response = client_admin_real_uow.post(f"/api/v1/admin/doors/{case.door}/override", json={
        "new_status": "NOT_INSTALLED", "reason_id": str(make_reason().id), "override_reason": "QA cancel"})
    assert response.status_code == 200, response.text
    assert all(matrix(client_admin_real_uow, path)["total"] == 0 for path in PATHS)
    second = make_installer(full_name="Second performer")
    db_session.get(DoorORM, case.door).installer_id = second.id
    db_session.commit()
    with SqlAlchemyUnitOfWork() as uow:
        DoorUseCases.mark_installed(uow, MarkDoorInstalled(company_id=case.company,
            actor_user_id=case.actor, door_id=case.door, expected_installer_id=second.id))
    for path in PATHS:
        data = matrix(client_admin_real_uow, path)
        assert data["total"] == 1
        item = data["items"][0]
        assert item["installer_id"] == str(second.id) and item["installed_doors"] == 1
        assert Decimal(item["payroll_total"]) == 250


def test_open_issues_follow_current_responsible_not_historical_performer(case, client_admin_real_uow, db_session, make_installer):
    activate(case)
    assert submit(case, "DOOR", "install").status_code == 200
    assert submit(case, "ADDON", "direct").status_code == 200
    second = make_installer(full_name="Responsible installer")
    db_session.get(DoorORM, case.door).installer_id = second.id
    # The second installer has their own recorded addon; attribution must come from the ledger.
    addon_work = db_session.query(CompletedWorkORM).filter_by(company_id=case.company, work_kind="ADDON").one()
    db_session.execute(text("SET LOCAL session_replication_role = 'replica'"))  # test-only tamper below the 0076 guard
    addon_work.installer_id = second.id
    db_session.add(IssueORM(company_id=case.company, door_id=case.door, title="QA open issue"))
    db_session.commit()
    for path in PATHS:
        rows = {row["installer_id"]: row for row in matrix(client_admin_real_uow, path)["items"]}
        assert rows[str(case.installer)]["open_issues"] == 0
        assert rows[str(second.id)]["open_issues"] == 1
        assert Decimal(rows[str(case.installer)]["payroll_total"]) == 250
        assert Decimal(rows[str(second.id)]["payroll_total"]) == Decimal("13.50")


@pytest.mark.parametrize("kind,channel,rate,expected", [
    ("DOOR", "install", "280", "280"), ("ADDON", "direct", "8", "12"),
])
def test_legacy_corrections_not_double_counted(case, client_admin_real_uow, db_session, kind, channel, rate, expected):
    assert submit(case, kind, channel).status_code == 200
    work = db_session.query(CompletedWorkORM).filter_by(company_id=case.company).one()
    response = client_admin_real_uow.post("/api/v1/admin/earnings/corrections", json={
        "completed_work_id": str(work.id), "rate_snapshot": rate, "reason": "QA adjustment"})
    assert response.status_code == 201, response.text
    activate(case)
    for path in PATHS:
        item = matrix(client_admin_real_uow, path)["items"][0]
        assert Decimal(item["payroll_total"]) == Decimal(expected)
        assert item["installed_doors"] == (1 if kind == "DOOR" else 0)
        assert Decimal(item["addons_done_qty"]) == (0 if kind == "DOOR" else Decimal("1.5"))


@pytest.mark.parametrize("kind,assigned", [("DOOR", True), ("DOOR", False), ("ADDON", True)])
def test_unrecorded_work_is_reconciliation_not_earned_money(case, client_admin_real_uow, db_session, kind, assigned):
    activate(case)
    installer_id = case.installer if assigned else None
    if kind == "DOOR":
        door = db_session.get(DoorORM, case.door)
        door.status, door.installed_at, door.installer_id = DoorStatus.INSTALLED, utcnow(), installer_id
    else:
        db_session.add(ProjectAddonFactORM(company_id=case.company, project_id=case.project,
            addon_type_id=case.addon, installer_id=installer_id, qty_done=Decimal("2"), done_at=utcnow()))
    db_session.commit()
    for path in PATHS:
        data = matrix(client_admin_real_uow, path)
        assert data["total"] == int(assigned)
        assert data["incomplete_items"] == int(assigned)
        assert data["unassigned_completed_works"] == int(not assigned)
        if assigned:
            item = data["items"][0]
            assert item["unrecorded_completed_works"] == 1
            assert item["performance_band"] == "INCOMPLETE"
            assert item["profit_total"] is None and item["margin_pct"] is None and item["avg_profit_per_door"] is None
            assert Decimal(item["payroll_total"]) == 0 and item["installed_doors"] == 0
            assert Decimal(item["addons_done_qty"]) == 0
    risk = client_admin_real_uow.get("/api/v1/admin/reports/risk-concentration")
    assert risk.status_code == 200, risk.text
    assert risk.json()["summary"]["incomplete_installers"] == int(assigned)
    assert risk.json()["summary"]["unassigned_completed_works"] == int(not assigned)


@pytest.mark.parametrize("missing", [False, True])
def test_csv_risk_and_missing_client_price_match_matrix(case, client_admin_real_uow, db_session, missing):
    activate(case)
    assert submit(case, "DOOR", "install").status_code == 200
    assert submit(case, "ADDON", "direct").status_code == 200
    if missing:
        db_session.delete(db_session.get(ProjectAddonPlanORM, case.plan))
        db_session.commit()
    row = matrix(client_admin_real_uow, PATHS[0])["items"][0]
    assert Decimal(row["payroll_total"]) == Decimal("263.50")
    assert row["missing_client_prices"] == int(missing)
    assert (row["profit_total"] is None) == missing
    risk = client_admin_real_uow.get("/api/v1/admin/reports/risk-concentration")
    assert risk.status_code == 200, risk.text
    assert risk.json()["installers"][0] == row
    assert risk.json()["summary"]["worst_installer_profit_total"] == row["profit_total"]
    response = client_admin_real_uow.get("/api/v1/admin/reports/executive/export")
    assert response.status_code == 200, response.text
    rows = {r["section"]: r for r in csv.DictReader(io.StringIO(response.text))}
    for section, profit_column in (("installers_matrix", "value_2"), ("installer_project_cross_view", "value_2")):
        assert rows[f"{section}_basis"]["metric"] == "FACTORY"
        assert rows[f"{section}_basis"]["value_1"] == "ledger_actuals"
        assert rows[f"{section}_basis"]["value_2"] == str(int(missing))
        assert rows[f"{section}_coverage"]["metric"] == str(case.installer)
        assert rows[f"{section}_coverage"]["value_4"] == str(int(missing))
        assert Decimal(rows[f"{section}_earnings"]["value_2"]) == Decimal(row["payroll_total"])
        if missing:
            assert rows[section][profit_column] == ""
        else:
            assert Decimal(rows[section][profit_column]) == Decimal(row["profit_total"])


@pytest.mark.parametrize("sort_dir", ["asc", "desc"])
def test_nulls_last_and_stable_pagination(case, client_admin_real_uow, db_session, make_installer, sort_dir):
    activate(case)
    assert submit(case, "DOOR", "install").status_code == 200
    source = db_session.query(CompletedWorkORM).filter_by(company_id=case.company).one()
    # Independent ledger groups with identical metrics exercise UUID tie-breaking.
    second = make_installer()
    db_session.add(CompletedWorkORM(company_id=case.company, project_id=case.project,
        installer_id=second.id, work_kind="DOOR", door_id=case.door, quantity=1,
        rate_snapshot=source.rate_snapshot, amount_snapshot=source.amount_snapshot,
        completed_at=utcnow(), entry_type="ORIGINAL"))
    missing = make_installer(full_name="Incomplete")
    db_session.add(ProjectAddonFactORM(company_id=case.company, project_id=case.project,
        addon_type_id=case.addon, installer_id=missing.id, qty_done=1, done_at=utcnow()))
    db_session.commit()
    for path in PATHS:
        pages = [matrix(client_admin_real_uow, path, f"limit=1&offset={i}&sort_dir={sort_dir}") for i in range(3)]
        assert all(p["total"] == 3 and p["incomplete_items"] == 1 for p in pages)
        ids = [p["items"][0]["installer_id"] for p in pages]
        assert len(set(ids)) == 3 and ids[0] < ids[1]
        assert ids[2] == str(missing.id)
        assert matrix(client_admin_real_uow, path, f"limit=1&sort_dir={sort_dir}")["items"][0]["installer_id"] == ids[0]


def test_foreign_work_excluded_and_missing_project_keeps_earned_amount(case, client_admin_real_uow, db_session, make_installer):
    activate(case)
    assert submit(case, "DOOR", "install").status_code == 200
    foreign_company = CompanyORM(name="Private installer report tenant")
    db_session.add(foreign_company)
    db_session.commit()
    foreign_installer = make_installer(company=foreign_company.id, full_name="Private installer")
    foreign_project = ProjectORM(company_id=foreign_company.id, name="Private site", address="QA", status="OK")
    db_session.add(foreign_project)
    db_session.commit()
    work = db_session.query(CompletedWorkORM).filter_by(company_id=case.company).one()
    db_session.execute(text("SET LOCAL session_replication_role = 'replica'"))  # test-only tamper below the 0076 guard
    work.project_id = foreign_project.id
    foreign_work = CompletedWorkORM(company_id=foreign_company.id, project_id=foreign_project.id,
        installer_id=foreign_installer.id, work_kind="DOOR", door_id=case.door,
        quantity=1, rate_snapshot=900, amount_snapshot=900, completed_at=utcnow(), entry_type="ORIGINAL")
    db_session.add(foreign_work)
    # No unmatched installed door in this deliberately corrupted-link fixture.
    db_session.get(DoorORM, case.door).status = DoorStatus.IN_PROGRESS
    db_session.commit()
    try:
        for project_id in (foreign_project.id, None):
            db_session.execute(text("SET LOCAL session_replication_role = 'replica'"))  # test-only tamper below the 0076 guard
            work.project_id = project_id
            db_session.commit()
            data = matrix(client_admin_real_uow, PATHS[1])
            assert data["total"] == 1
            item = data["items"][0]
            assert item["project_id"] is None and item["project_name"] is None
            assert item["installer_id"] == str(case.installer)
            assert Decimal(item["payroll_total"]) == 250
    finally:
        db_session.rollback()
        db_session.execute(text("SET LOCAL session_replication_role = 'replica'"))  # test-only cleanup below the 0076 guard
        db_session.delete(foreign_work)
        db_session.delete(foreign_project)
        db_session.delete(foreign_installer)
        db_session.delete(foreign_company)
        db_session.commit()


@pytest.mark.parametrize("path", (*PATHS, "risk-concentration", "executive/export"))
def test_installer_denied_and_invalid_confirmation_fails_closed(case, client_admin_real_uow, db_session, path):
    version, _ = activate(case)
    url = f"/api/v1/admin/reports/{path}"
    assert case.client.get(url).status_code == 403
    receipt = db_session.query(FactoryPriceApprovalORM).filter_by(price_list_id=version.id).one()
    receipt.snapshot_hash = "0" * 64
    db_session.commit()
    assert client_admin_real_uow.get(url).status_code == 409
