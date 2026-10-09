import csv
import io
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.modules.doors.application.commands import MarkDoorInstalled
from app.modules.doors.application.use_cases import DoorUseCases
from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.earnings.infrastructure.models import ClientPriceSnapshotORM, CompletedWorkORM
from app.modules.identity.infrastructure.models import CompanyORM
from app.modules.installers.infrastructure.models import InstallerORM
from app.modules.projects.infrastructure.models import ProjectORM
from app.modules.rates.infrastructure.approval_models import FactoryPriceApprovalORM
from app.shared.infrastructure.db.base import utcnow
from app.shared.infrastructure.db.uow_sqlalchemy import SqlAlchemyUnitOfWork
from test_factory_earnings import case, activate, confirmed, submit


PATH = "/api/v1/admin/reports/installers-kpi"
DAY = datetime(2026, 10, 1, tzinfo=timezone.utc)


def kpi(client, **params):
    response = client.get(PATH, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def unrecorded(case, session, installer, suffix="missing", at=DAY):
    door = DoorORM(company_id=case.company, project_id=case.project,
        door_type_id=case.door_type, unit_label=suffix, our_price=500,
        status=DoorStatus.INSTALLED, installer_id=installer, installed_at=at,
        installer_rate_snapshot=999)
    session.add(door)
    session.commit()
    return door


def test_confirmed_but_inactive_preserves_legacy_calculation(case, db_session, client_admin_real_uow):
    unrecorded(case, db_session, case.installer)
    confirmed(case.company, case.actor, case.items)
    data = kpi(client_admin_real_uow)
    assert data["pricing_mode"] == "LEGACY"
    assert data["total"] == 1 and data["incomplete_items"] == 0
    item = data["items"][0]
    assert item["installed_doors"] == 1
    assert Decimal(item["payroll_total"]) == 999
    assert item["unrecorded_completed_works"] == 0


@pytest.mark.parametrize("assigned", [True, False])
def test_unrecorded_installations_do_not_invent_earnings(case, db_session, client_admin_real_uow, assigned):
    activate(case)
    unrecorded(case, db_session, case.installer if assigned else None)
    data = kpi(client_admin_real_uow, date_from=DAY.isoformat(), date_to=(DAY + timedelta(days=1)).isoformat())
    assert data["pricing_mode"] == "FACTORY"
    assert data["total"] == int(assigned) and data["incomplete_items"] == int(assigned)
    assert data["unassigned_completed_works"] == int(not assigned)
    if assigned:
        row = data["items"][0]
        assert row["installed_doors"] == 0 and row["unrecorded_completed_works"] == 1
        assert Decimal(row["payroll_total"]) == Decimal(row["revenue_total"]) == 0
        assert row["profit_total"] is None
    outside = kpi(client_admin_real_uow, date_from=(DAY + timedelta(days=1)).isoformat())
    assert outside["total"] == outside["unassigned_completed_works"] == 0
    export = client_admin_real_uow.get(f"{PATH}/export")
    assert export.status_code == 200, export.text
    rows = list(csv.DictReader(io.StringIO(export.text)))
    summary = rows[0]
    assert summary["record_type"] == "summary" and summary["pricing_mode"] == "FACTORY"
    assert summary["unassigned_completed_works"] == str(int(not assigned))
    assert summary["payroll_total"] == "" and summary["accounting_basis"] == "active_door_work_by_completion_time"
    if assigned:
        assert rows[1]["record_type"] == "installer" and rows[1]["profit_total"] == ""
        assert Decimal(rows[1]["payroll_total"]) == 0
    else:
        assert len(rows) == 1


def test_price_changes_and_reassignment_do_not_move_historical_kpi(case, db_session, client_admin_real_uow, make_installer):
    version, _ = activate(case)
    assert submit(case, "DOOR", "install").status_code == 200
    assert submit(case, "ADDON", "direct").status_code == 200
    before = list(db_session.query(CompletedWorkORM.id, CompletedWorkORM.amount_snapshot)
                  .filter_by(company_id=case.company).order_by(CompletedWorkORM.id))
    other = make_installer(full_name="Current assignee")
    door = db_session.get(DoorORM, case.door)
    door.installer_id, door.installer_rate_snapshot, door.our_price = other.id, Decimal("1234"), Decimal("800")
    db_session.get(InstallerORM, case.installer).is_active = False
    db_session.commit()
    activate(case, expected=1, previous=version.id, door_price="300")
    data = kpi(client_admin_real_uow)
    assert data["total"] == 1 and data["incomplete_items"] == 0
    row = data["items"][0]
    assert row["installer_id"] == str(case.installer) and row["installed_doors"] == 1
    assert Decimal(row["payroll_total"]) == 250  # Addons are outside this report.
    assert Decimal(row["revenue_total"]) == 500  # Saved client price, not the edited door.
    assert Decimal(row["profit_total"]) == 250
    assert before == list(db_session.query(CompletedWorkORM.id, CompletedWorkORM.amount_snapshot)
                          .filter_by(company_id=case.company).order_by(CompletedWorkORM.id))


def test_period_is_half_open_and_uses_execution_not_door_status_timestamp(case, db_session, client_admin_real_uow):
    activate(case)
    assert submit(case, "DOOR", "install").status_code == 200
    db_session.query(CompletedWorkORM).filter_by(company_id=case.company).one().completed_at = DAY
    db_session.get(DoorORM, case.door).installed_at = DAY + timedelta(days=2)
    db_session.commit()
    exact = kpi(client_admin_real_uow, date_from=DAY.isoformat(), date_to=(DAY + timedelta(days=1)).isoformat())
    assert exact["items"][0]["installed_doors"] == 1
    before = kpi(client_admin_real_uow, date_to=DAY.isoformat())
    after = kpi(client_admin_real_uow, date_from=(DAY + timedelta(days=1)).isoformat())
    assert before["total"] == after["total"] == 0
    assert after["incomplete_items"] == 0  # Active evidence outside the slice is not a gap.


def test_partial_coverage_keeps_known_payroll_without_inventing_missing_payroll(case, db_session, client_admin_real_uow):
    activate(case)
    assert submit(case, "DOOR", "install").status_code == 200
    unrecorded(case, db_session, case.installer)
    work = db_session.query(CompletedWorkORM).filter_by(company_id=case.company).one()
    db_session.query(ClientPriceSnapshotORM).filter_by(completed_work_id=work.id).delete()
    db_session.get(DoorORM, case.door).our_price = Decimal("750")
    db_session.commit()
    data = kpi(client_admin_real_uow)
    row = data["items"][0]
    assert data["incomplete_items"] == 1 and row["installed_doors"] == 1
    assert row["unrecorded_completed_works"] == 1 and row["missing_client_prices"] == 0
    assert Decimal(row["payroll_total"]) == 250
    assert Decimal(row["revenue_total"]) == 750  # Explicit client-price fallback, not installer-price fallback.
    assert row["profit_total"] is None


def test_stale_installed_status_after_reversal_is_a_gap_not_new_payroll(case, db_session, client_admin_real_uow, make_reason):
    activate(case)
    assert submit(case, "DOOR", "install").status_code == 200
    response = client_admin_real_uow.post(f"/api/v1/admin/doors/{case.door}/override", json={
        "new_status": "NOT_INSTALLED", "reason_id": str(make_reason().id), "override_reason": "QA cancel"})
    assert response.status_code == 200, response.text
    door = db_session.get(DoorORM, case.door)
    door.status, door.installed_at = DoorStatus.INSTALLED, DAY
    db_session.commit()
    row = kpi(client_admin_real_uow)["items"][0]
    assert row["installed_doors"] == 0 and row["unrecorded_completed_works"] == 1
    assert Decimal(row["payroll_total"]) == 0 and row["profit_total"] is None


def test_later_cancel_removes_old_performance_and_reinstall_credits_new_performer(case, db_session, client_admin_real_uow, make_reason, make_installer):
    activate(case)
    assert submit(case, "DOOR", "install").status_code == 200
    db_session.query(CompletedWorkORM).filter_by(company_id=case.company).one().completed_at = DAY
    db_session.commit()
    response = client_admin_real_uow.post(f"/api/v1/admin/doors/{case.door}/override", json={
        "new_status": "NOT_INSTALLED", "reason_id": str(make_reason().id), "override_reason": "QA cancel"})
    assert response.status_code == 200, response.text
    assert kpi(client_admin_real_uow, date_to=(DAY + timedelta(days=1)).isoformat())["total"] == 0
    second = make_installer(full_name="Second performer")
    db_session.get(DoorORM, case.door).installer_id = second.id
    db_session.commit()
    with SqlAlchemyUnitOfWork() as uow:
        DoorUseCases.mark_installed(uow, MarkDoorInstalled(company_id=case.company,
            actor_user_id=case.actor, door_id=case.door, expected_installer_id=second.id))
    rows = kpi(client_admin_real_uow)["items"]
    assert len(rows) == 1 and rows[0]["installer_id"] == str(second.id)
    assert Decimal(rows[0]["payroll_total"]) == 250


def test_correction_preserves_completion_period_and_client_snapshot(case, db_session, client_admin_real_uow):
    assert submit(case, "DOOR", "install").status_code == 200
    work = db_session.query(CompletedWorkORM).filter_by(company_id=case.company).one()
    work.completed_at = DAY
    db_session.commit()
    response = client_admin_real_uow.post("/api/v1/admin/earnings/corrections", json={
        "completed_work_id": str(work.id), "rate_snapshot": "280", "reason": "QA corrected rate"})
    assert response.status_code == 201, response.text
    db_session.get(DoorORM, case.door).our_price = Decimal("900")
    db_session.commit()
    activate(case)
    rows = kpi(client_admin_real_uow, date_from=DAY.isoformat(), date_to=(DAY + timedelta(days=1)).isoformat())["items"]
    assert len(rows) == 1 and rows[0]["installed_doors"] == 1
    assert Decimal(rows[0]["payroll_total"]) == 280
    assert Decimal(rows[0]["revenue_total"]) == 500


@pytest.mark.parametrize("direction", ["asc", "desc"])
def test_coverage_is_unpaginated_null_profit_last_and_ties_stable(case, db_session, client_admin_real_uow, make_installer, direction):
    activate(case)
    assert submit(case, "DOOR", "install").status_code == 200
    second = make_installer(full_name="Factory installer")
    source = db_session.query(CompletedWorkORM).filter_by(company_id=case.company).one()
    db_session.add(CompletedWorkORM(company_id=case.company, project_id=case.project,
        installer_id=second.id, work_kind="DOOR", door_id=case.door, quantity=1,
        rate_snapshot=source.rate_snapshot, amount_snapshot=source.amount_snapshot,
        completed_at=utcnow(), entry_type="ORIGINAL"))
    db_session.get(InstallerORM, case.installer).full_name = second.full_name
    missing = make_installer(full_name="Missing performer")
    unrecorded(case, db_session, missing.id)
    unrecorded(case, db_session, None, suffix="unassigned")
    pages = [kpi(client_admin_real_uow, limit=1, offset=index, sort_by="profit_total", sort_dir=direction) for index in range(4)]
    assert all(p["total"] == 3 and p["incomplete_items"] == 1 and p["unassigned_completed_works"] == 1 for p in pages)
    ids = [p["items"][0]["installer_id"] for p in pages[:3]]
    assert ids[:2] == sorted([str(case.installer), str(second.id)])
    assert ids[2] == str(missing.id) and pages[3]["items"] == []


def test_missing_client_price_keeps_payroll_and_tenant_isolation(case, db_session, client_admin_real_uow, make_installer):
    activate(case)
    assert submit(case, "DOOR", "install").status_code == 200
    work = db_session.query(CompletedWorkORM).filter_by(company_id=case.company).one()
    db_session.query(ClientPriceSnapshotORM).filter_by(completed_work_id=work.id).delete()
    foreign = CompanyORM(name="Private KPI tenant")
    db_session.add(foreign)
    db_session.commit()
    foreign_installer = make_installer(company=foreign.id, full_name="Private performer")
    project = ProjectORM(company_id=foreign.id, name="Private site", address="QA", status="OK")
    db_session.add(project)
    db_session.flush()
    # An intentionally corrupt foreign subject link must not disclose its price.
    foreign_door = DoorORM(company_id=foreign.id, project_id=project.id,
        door_type_id=case.door_type, unit_label="private", our_price=9999, status=DoorStatus.IN_PROGRESS)
    db_session.add(foreign_door)
    db_session.flush()
    work.door_id = foreign_door.id
    db_session.get(DoorORM, case.door).status = DoorStatus.IN_PROGRESS
    foreign_work = CompletedWorkORM(company_id=foreign.id, project_id=project.id,
        installer_id=foreign_installer.id, work_kind="DOOR", door_id=foreign_door.id,
        quantity=1, rate_snapshot=9999, amount_snapshot=9999, completed_at=utcnow(), entry_type="ORIGINAL")
    db_session.add(foreign_work)
    db_session.commit()
    try:
        data = kpi(client_admin_real_uow)
        assert data["total"] == data["incomplete_items"] == 1
        row = data["items"][0]
        assert row["installer_id"] == str(case.installer)
        assert Decimal(row["payroll_total"]) == 250 and Decimal(row["revenue_total"]) == 0
        assert row["missing_client_prices"] == 1 and row["profit_total"] is None
        exported = client_admin_real_uow.get(f"{PATH}/export")
        assert "Private" not in exported.text and "9999" not in exported.text
    finally:
        work.door_id = case.door
        db_session.delete(foreign_work)
        db_session.flush()
        db_session.delete(foreign_door)
        db_session.flush()
        db_session.delete(project)
        db_session.delete(foreign_installer)
        db_session.delete(foreign)
        db_session.commit()


@pytest.mark.parametrize("suffix", ["", "/export"])
def test_installer_denied_and_corrupt_confirmation_fails_closed(case, db_session, client_admin_real_uow, suffix):
    version, _ = activate(case)
    assert case.client.get(PATH + suffix).status_code == 403
    db_session.query(FactoryPriceApprovalORM).filter_by(price_list_id=version.id).one().snapshot_hash = "0" * 64
    db_session.commit()
    response = client_admin_real_uow.get(PATH + suffix)
    assert response.status_code == 409, response.text
