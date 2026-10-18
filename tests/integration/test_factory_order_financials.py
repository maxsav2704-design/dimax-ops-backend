import csv
import io
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.earnings.infrastructure.models import ClientPriceSnapshotORM, CompletedWorkORM
from app.modules.identity.infrastructure.models import CompanyORM
from app.modules.issues.infrastructure.models import IssueORM
from app.modules.projects.infrastructure.models import ProjectORM
from app.modules.rates.infrastructure.approval_models import FactoryPriceApprovalORM
from app.shared.infrastructure.db.base import utcnow
from test_factory_earnings import case, confirmed, submit
from test_factory_installer_details import activate


@pytest.fixture(autouse=True)
def order_number(case, db_session):
    db_session.get(DoorORM, case.door).order_number = "ORDER-1"
    db_session.commit()


def orders(client, **params):
    response = client.get("/api/v1/admin/reports/order-numbers-kpi", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def add_door(session, case, order_number, *, project_id=None, status=DoorStatus.IN_PROGRESS):
    door = DoorORM(company_id=case.company, project_id=project_id or case.project,
        door_type_id=case.door_type, installer_id=case.installer, unit_label=order_number,
        status=status, order_number=order_number, our_price=500, version=0, is_locked=False)
    session.add(door)
    session.flush()
    return door


def test_unactivated_confirmation_keeps_legacy(case, client_admin_real_uow, db_session):
    door = db_session.get(DoorORM, case.door)
    door.status, door.installed_at = DoorStatus.INSTALLED, utcnow()
    db_session.commit()
    confirmed(case.company, case.actor, case.items)
    data = orders(client_admin_real_uow)
    assert data["pricing_mode"] == "LEGACY" and data["incomplete_orders"] == 0
    assert Decimal(data["items"][0]["payroll_total"]) == 999


@pytest.mark.parametrize("snapshot", [True, False])
def test_recorded_money_survives_assignment_and_price_changes_without_issue_multiplication(
    case, client_admin_real_uow, db_session, make_installer, snapshot,
):
    version, _ = activate(case)
    assert submit(case, "DOOR", "install").status_code == 200
    assert submit(case, "ADDON", "direct").status_code == 200
    work = db_session.query(CompletedWorkORM).filter_by(company_id=case.company, work_kind="DOOR").one()
    if not snapshot:
        db_session.query(ClientPriceSnapshotORM).filter_by(completed_work_id=work.id).delete()
    door = db_session.get(DoorORM, case.door)
    door.installer_id, door.installer_rate_snapshot, door.our_price = make_installer().id, 1234, 900
    second = add_door(db_session, case, "ORDER-1")
    db_session.add_all([IssueORM(company_id=case.company, door_id=door_id, title=f"QA issue {i}")
                       for i, door_id in enumerate((case.door, second.id))])
    db_session.commit()
    activate(case, expected=1, previous=version.id, door_price="300", addon_price="12")
    before = list(db_session.query(CompletedWorkORM.id, CompletedWorkORM.amount_snapshot)
                  .filter_by(company_id=case.company).order_by(CompletedWorkORM.id))
    data = orders(client_admin_real_uow)
    row = data["items"][0]
    assert data["pricing_mode"] == row["pricing_mode"] == "FACTORY"
    assert row["installed_doors"] == row["recorded_installations"] == 1
    assert row["total_doors"] == row["open_issues"] == 2 and row["completion_pct"] == 50
    assert Decimal(row["payroll_total"]) == 250  # Addon money is outside this door-only report.
    assert Decimal(row["planned_revenue_total"]) == 1400
    assert Decimal(row["installed_revenue_total"]) == (500 if snapshot else 900)
    assert Decimal(row["profit_total"]) == (250 if snapshot else 650)
    assert before == list(db_session.query(CompletedWorkORM.id, CompletedWorkORM.amount_snapshot)
                          .filter_by(company_id=case.company).order_by(CompletedWorkORM.id))


@pytest.mark.parametrize("stale_installed", [False, True])
def test_cancellation_and_stale_status_do_not_restore_legacy_money(case, client_admin_real_uow, db_session, make_reason, stale_installed):
    activate(case)
    assert submit(case, "DOOR", "install").status_code == 200
    response = client_admin_real_uow.post(f"/api/v1/admin/doors/{case.door}/override", json={
        "new_status": "NOT_INSTALLED", "reason_id": str(make_reason().id), "override_reason": "QA cancel"})
    assert response.status_code == 200, response.text
    db_session.expire_all()
    if stale_installed:
        db_session.get(DoorORM, case.door).status = DoorStatus.INSTALLED
        db_session.commit()
    row = orders(client_admin_real_uow)["items"][0]
    assert Decimal(row["payroll_total"]) == Decimal(row["installed_revenue_total"]) == row["recorded_installations"] == 0
    assert row["unrecorded_completed_works"] == row["installed_doors"] == int(stale_installed)
    assert (row["profit_total"] is None) == stale_installed


def test_correction_uses_one_effective_work_and_original_client_snapshot(case, client_admin_real_uow, db_session):
    assert submit(case, "DOOR", "install").status_code == 200
    work = db_session.query(CompletedWorkORM).filter_by(company_id=case.company).one()
    response = client_admin_real_uow.post("/api/v1/admin/earnings/corrections", json={
        "completed_work_id": str(work.id), "rate_snapshot": "280", "reason": "QA agreed correction"})
    assert response.status_code == 201, response.text
    activate(case)
    db_session.get(DoorORM, case.door).our_price = 800
    db_session.commit()
    row = orders(client_admin_real_uow)["items"][0]
    assert row["recorded_installations"] == 1
    assert Decimal(row["payroll_total"]) == 280
    assert Decimal(row["installed_revenue_total"]) == 500
    assert Decimal(row["profit_total"]) == 220


def test_missing_evidence_stays_in_operational_progress_but_not_money_or_profit(case, client_admin_real_uow, db_session):
    activate(case)
    door = db_session.get(DoorORM, case.door)
    door.status, door.installed_at, door.installer_id = DoorStatus.INSTALLED, utcnow(), None
    db_session.commit()
    data = orders(client_admin_real_uow)
    row = data["items"][0]
    assert data["incomplete_orders"] == row["unrecorded_completed_works"] == row["missing_rates_installed_doors"] == 1
    assert row["installed_doors"] == 1 and row["completion_pct"] == 100
    assert Decimal(row["payroll_total"]) == Decimal(row["installed_revenue_total"]) == row["recorded_installations"] == 0
    assert row["profit_total"] is None
    risk = client_admin_real_uow.get("/api/v1/admin/reports/risk-concentration")
    assert risk.status_code == 200, risk.text
    assert risk.json()["orders"][0] == row
    assert risk.json()["summary"]["worst_order_profit_total"] is None
    assert risk.json()["summary"]["incomplete_orders"] == risk.json()["summary"]["order_rows_total"] == 1
    response = client_admin_real_uow.get("/api/v1/admin/reports/order-numbers-kpi/export")
    assert response.status_code == 200, response.text
    exported = list(csv.DictReader(io.StringIO(response.text)))
    assert exported[0]["record_type"] == "summary" and exported[0]["incomplete_orders"] == "1"
    assert exported[1]["profit_total"] == "" and exported[1]["recorded_installations"] == "0"
    response = client_admin_real_uow.get("/api/v1/admin/reports/executive/export")
    assert response.status_code == 200, response.text
    executive = {r["section"]: r for r in csv.DictReader(io.StringIO(response.text))}
    assert executive["order_financial_basis"]["metric"] == "FACTORY"
    assert executive["order_financial_basis"]["value_2"] == "1"
    assert executive["order_financials"]["value_3"] == ""


def test_normalized_groups_literal_search_and_current_project_scope(case, client_admin_real_uow, db_session):
    activate(case)
    db_session.get(DoorORM, case.door).order_number = " A_%/1 "
    other = ProjectORM(company_id=case.company, name="Second project", address="QA", status="OK")
    db_session.add(other)
    db_session.flush()
    add_door(db_session, case, "A_%/1", project_id=other.id, status=DoorStatus.NOT_INSTALLED)
    add_door(db_session, case, "A-xx/1")
    add_door(db_session, case, "   ")
    db_session.commit()
    data = orders(client_admin_real_uow, q="a_%/1")
    assert data["total"] == 1 and data["items"][0]["order_number"] == "A_%/1"
    assert data["items"][0]["total_doors"] == 2
    assert data["items"][0]["not_installed_doors"] == 1
    assert orders(client_admin_real_uow, project_id=str(case.project), q="a_%/1")["items"][0]["total_doors"] == 1
    assert orders(client_admin_real_uow)["total"] == 2
    assert orders(client_admin_real_uow, q="no match")["items"] == []


@pytest.mark.parametrize("direction", ["asc", "desc"])
def test_stable_pages_put_unknown_profit_last_and_count_gaps_before_limit(case, client_admin_real_uow, db_session, direction):
    activate(case)
    assert submit(case, "DOOR", "install").status_code == 200
    db_session.get(DoorORM, case.door).order_number = "A"
    second = add_door(db_session, case, "B", status=DoorStatus.INSTALLED)
    db_session.add(CompletedWorkORM(company_id=case.company, project_id=case.project,
        installer_id=case.installer, door_id=second.id, work_kind="DOOR", quantity=1,
        rate_snapshot=250, amount_snapshot=250, completed_at=utcnow(), entry_type="ORIGINAL"))
    add_door(db_session, case, "Z", status=DoorStatus.INSTALLED)
    db_session.commit()
    pages = [orders(client_admin_real_uow, sort_by="profit_total", sort_dir=direction, limit=1, offset=i) for i in range(3)]
    assert all(p["total"] == 3 and p["incomplete_orders"] == 1 for p in pages)
    assert [p["items"][0]["order_number"] for p in pages] == ["A", "B", "Z"]
    assert pages[-1]["items"][0]["profit_total"] is None
    assert orders(client_admin_real_uow, limit=1, offset=3)["items"] == []


@pytest.mark.parametrize("label", ["=1+1", "+100", "-20", "@SUM(1)", "\t=1+1"])
def test_csv_order_label_is_not_an_excel_formula(case, client_admin_real_uow, db_session, label):
    activate(case)
    db_session.get(DoorORM, case.door).order_number = label
    db_session.commit()
    response = client_admin_real_uow.get("/api/v1/admin/reports/order-numbers-kpi/export")
    assert response.status_code == 200, response.text
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert rows[1]["order_number"] == "'" + label
    assert orders(client_admin_real_uow)["items"][0]["order_number"] == label


def test_empty_export_includes_basis_without_inventing_financial_totals(case, client_admin_real_uow):
    activate(case)
    response = client_admin_real_uow.get("/api/v1/admin/reports/order-numbers-kpi/export?q=absent")
    assert response.status_code == 200, response.text
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert len(rows) == 1 and rows[0]["record_type"] == "summary"
    assert rows[0]["total_orders"] == "0" and rows[0]["payroll_total"] == ""


def test_tenant_isolation_including_corrupt_foreign_links(case, client_admin_real_uow, db_session):
    activate(case)
    assert submit(case, "DOOR", "install").status_code == 200
    foreign = CompanyORM(name="Private order tenant")
    db_session.add(foreign)
    db_session.flush()
    project = ProjectORM(company_id=foreign.id, name="Private order site", address="QA", status="OK")
    db_session.add(project)
    db_session.flush()
    door = DoorORM(company_id=foreign.id, project_id=project.id, door_type_id=case.door_type,
        order_number="PRIVATE", unit_label="QA foreign", status=DoorStatus.INSTALLED,
        our_price=9999, version=0, is_locked=False)
    db_session.add(door)
    db_session.flush()
    work = CompletedWorkORM(company_id=foreign.id, project_id=project.id, installer_id=case.installer,
        door_id=case.door, work_kind="DOOR", quantity=1, rate_snapshot=999, amount_snapshot=999,
        completed_at=utcnow(), entry_type="ORIGINAL")
    issue = IssueORM(company_id=foreign.id, door_id=case.door, title="Private issue")
    db_session.add_all([work, issue])
    db_session.commit()
    try:
        data = orders(client_admin_real_uow)
        assert data["total"] == 1 and data["items"][0]["open_issues"] == 0
        assert Decimal(data["items"][0]["payroll_total"]) == 250
        assert "PRIVATE" not in str(data)
        assert orders(client_admin_real_uow, project_id=str(project.id))["total"] == 0
    finally:
        db_session.rollback()
        db_session.execute(text("SET LOCAL session_replication_role = 'replica'"))  # test-only cleanup below the 0076 guard
        for entity in (work, issue, door, project, foreign):
            db_session.delete(entity)
            db_session.flush()
        db_session.commit()


@pytest.mark.parametrize("path", ["order-numbers-kpi", "order-numbers-kpi/export", "risk-concentration", "executive/export"])
def test_permissions_and_invalid_factory_receipt(case, client_admin_real_uow, db_session, path):
    version, _ = activate(case)
    url = f"/api/v1/admin/reports/{path}"
    assert case.client.get(url).status_code == 403
    db_session.query(FactoryPriceApprovalORM).filter_by(price_list_id=version.id).one().snapshot_hash = "0" * 64
    db_session.commit()
    assert client_admin_real_uow.get(url).status_code == 409
