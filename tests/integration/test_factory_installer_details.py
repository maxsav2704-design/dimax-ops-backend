from decimal import Decimal

import pytest

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
from app.shared.domain.errors import Conflict
from app.shared.infrastructure.db.base import utcnow
from app.shared.infrastructure.db.uow_sqlalchemy import SqlAlchemyUnitOfWork
from test_factory_earnings import case, activate as activate_price, confirmed, submit


def activate(case, **kwargs):
    try:
        return activate_price(case, **kwargs)
    except Conflict as error:
        error.add_note(f"Test activation rejected: {error.details}")
        raise


def details(client, installer_id):
    response = client.get(f"/api/v1/admin/reports/installers-kpi/{installer_id}")
    assert response.status_code == 200, response.text
    return response.json()


def test_confirmation_without_activation_preserves_legacy(case, client_admin_real_uow, db_session):
    door = db_session.get(DoorORM, case.door)
    door.status, door.installed_at = DoorStatus.INSTALLED, utcnow()
    db_session.commit()
    confirmed(case.company, case.actor, case.items)
    data = details(client_admin_real_uow, case.installer)
    assert data["pricing_mode"] == "LEGACY"
    assert Decimal(data["payroll_total"]) == 999


@pytest.mark.parametrize("assignment", ["other", "none"])
def test_historical_performer_matches_matrix_after_reassignment_and_price_change(
    case, client_admin_real_uow, db_session, make_installer, assignment,
):
    version, _ = activate(case)
    assert submit(case, "DOOR", "install").status_code == 200
    assert submit(case, "ADDON", "direct").status_code == 200
    other = make_installer(full_name="New responsible installer")
    door = db_session.get(DoorORM, case.door)
    door.order_number, door.installer_rate_snapshot = " ORDER-101 ", Decimal("1234")
    door.installer_id = other.id if assignment == "other" else None
    db_session.query(ProjectAddonFactORM).filter_by(company_id=case.company).one().installer_id = other.id
    db_session.get(InstallerORM, case.installer).is_active = False
    db_session.commit()
    activate(case, expected=1, previous=version.id, door_price="300", addon_price="12")
    before = list(db_session.query(CompletedWorkORM.id, CompletedWorkORM.amount_snapshot)
                  .filter_by(company_id=case.company).order_by(CompletedWorkORM.id))
    data = details(client_admin_real_uow, case.installer)
    assert data["pricing_mode"] == "FACTORY"
    assert data["installed_doors"] == data["active_projects"] == data["order_numbers"] == 1
    assert Decimal(data["payroll_total"]) == Decimal("263.50")
    assert Decimal(data["addons_done_qty"]) == Decimal("1.50")
    assert Decimal(data["addon_payroll_total"]) == Decimal("13.50")
    assert Decimal(data["addon_profit_total"]) == Decimal("16.50")
    assert Decimal(data["revenue_total"]) == 530
    assert Decimal(data["profit_total"]) == Decimal("266.50")
    project, order = data["top_projects"][0], data["order_breakdown"][0]
    assert project["project_id"] == str(case.project) and project["payroll_total"] == data["payroll_total"]
    assert order["order_number"] == "ORDER-101" and Decimal(order["payroll_total"]) == 250
    matrix = client_admin_real_uow.get("/api/v1/admin/reports/installers-profitability-matrix").json()["items"][0]
    for key in ("installed_doors", "addons_done_qty", "revenue_total", "payroll_total", "profit_total"):
        assert data[key] == matrix[key]
    assert Decimal(details(client_admin_real_uow, other.id)["payroll_total"]) == 0
    assert before == list(db_session.query(CompletedWorkORM.id, CompletedWorkORM.amount_snapshot)
                          .filter_by(company_id=case.company).order_by(CompletedWorkORM.id))


def test_cancel_and_reinstall_only_credit_new_work(case, client_admin_real_uow, db_session, make_reason, make_installer):
    activate(case)
    assert submit(case, "DOOR", "install").status_code == 200
    response = client_admin_real_uow.post(f"/api/v1/admin/doors/{case.door}/override", json={
        "new_status": "NOT_INSTALLED", "reason_id": str(make_reason().id), "override_reason": "QA cancel"})
    assert response.status_code == 200, response.text
    second = make_installer()
    db_session.get(DoorORM, case.door).installer_id = second.id
    db_session.commit()
    with SqlAlchemyUnitOfWork() as uow:
        DoorUseCases.mark_installed(uow, MarkDoorInstalled(company_id=case.company,
            actor_user_id=case.actor, door_id=case.door, expected_installer_id=second.id))
    first = details(client_admin_real_uow, case.installer)
    assert Decimal(first["payroll_total"]) == first["installed_doors"] == first["active_projects"] == 0
    assert first["top_projects"] == first["order_breakdown"] == []
    assert Decimal(details(client_admin_real_uow, second.id)["payroll_total"]) == 250


def test_addon_reversal_does_not_reappear_as_unrecorded_work(case, client_admin_real_uow, db_session):
    activate(case)
    assert submit(case, "ADDON", "direct").status_code == 200
    work = db_session.query(CompletedWorkORM).filter_by(company_id=case.company).one()
    db_session.add(CompletedWorkORM(company_id=case.company, project_id=case.project,
        installer_id=case.installer, work_kind="ADDON", addon_fact_id=work.addon_fact_id,
        quantity=work.quantity, rate_snapshot=-work.rate_snapshot, amount_snapshot=-work.amount_snapshot,
        completed_at=utcnow(), entry_type="REVERSAL", correction_ref_id=work.id))
    db_session.commit()
    data = details(client_admin_real_uow, case.installer)
    assert data["unrecorded_completed_works"] == data["active_projects"] == 0
    assert Decimal(data["addon_payroll_total"]) == Decimal(data["addons_done_qty"]) == 0
    assert data["top_projects"] == []


@pytest.mark.parametrize("kind,channel,rate,total", [("DOOR", "install", "280", "280"), ("ADDON", "direct", "8", "12")])
def test_legacy_correction_counted_once(case, client_admin_real_uow, db_session, kind, channel, rate, total):
    assert submit(case, kind, channel).status_code == 200
    work = db_session.query(CompletedWorkORM).filter_by(company_id=case.company).one()
    response = client_admin_real_uow.post("/api/v1/admin/earnings/corrections", json={
        "completed_work_id": str(work.id), "rate_snapshot": rate, "reason": "QA adjustment"})
    assert response.status_code == 201, response.text
    activate(case)
    data = details(client_admin_real_uow, case.installer)
    assert Decimal(data["payroll_total"]) == Decimal(total)
    assert data["installed_doors"] == int(kind == "DOOR")
    assert Decimal(data["addons_done_qty"]) == (Decimal("1.50") if kind == "ADDON" else 0)


@pytest.mark.parametrize("kind", ["DOOR", "ADDON"])
def test_unrecorded_work_never_invents_earnings_or_profit(case, client_admin_real_uow, db_session, kind):
    activate(case)
    if kind == "DOOR":
        door = db_session.get(DoorORM, case.door)
        door.status, door.installed_at, door.order_number = DoorStatus.INSTALLED, utcnow(), "QA-MISSING"
    else:
        db_session.add(ProjectAddonFactORM(company_id=case.company, project_id=case.project,
            addon_type_id=case.addon, installer_id=case.installer, qty_done=2, done_at=utcnow()))
    db_session.commit()
    data = details(client_admin_real_uow, case.installer)
    assert data["unrecorded_completed_works"] == 1
    assert data["profit_total"] is None
    assert (data["addon_profit_total"] is None) == (kind == "ADDON")
    assert Decimal(data["payroll_total"]) == data["installed_doors"] == Decimal(data["addons_done_qty"]) == 0
    assert data["top_projects"][0]["profit_total"] is None
    assert len(data["order_breakdown"]) == int(kind == "DOOR")


def test_missing_addon_plan_keeps_payroll_and_marks_partial_profit(case, client_admin_real_uow, db_session):
    activate(case)
    assert submit(case, "DOOR", "install").status_code == 200
    assert submit(case, "ADDON", "direct").status_code == 200
    db_session.delete(db_session.get(ProjectAddonPlanORM, case.plan))
    db_session.commit()
    data = details(client_admin_real_uow, case.installer)
    assert data["missing_client_prices"] == data["addon_missing_client_prices"] == data["missing_addon_plans_facts"] == 1
    assert data["profit_total"] is data["addon_profit_total"] is None
    assert Decimal(data["payroll_total"]) == Decimal("263.50")


def test_open_issues_follow_current_assignee_even_without_financial_rows(case, client_admin_real_uow, db_session, make_installer):
    activate(case)
    assert submit(case, "DOOR", "install").status_code == 200
    second = make_installer()
    db_session.get(DoorORM, case.door).installer_id = second.id
    db_session.add(IssueORM(company_id=case.company, door_id=case.door, title="QA access"))
    db_session.commit()
    first, current = details(client_admin_real_uow, case.installer), details(client_admin_real_uow, second.id)
    assert first["open_issues"] == first["top_projects"][0]["open_issues"] == 0
    assert current["open_issues"] == 1 and current["top_projects"] == []


def test_prelimit_counts_and_stable_order_for_project_and_order_breakdowns(case, client_admin_real_uow, db_session):
    activate(case)
    # An addon-only project participates in projects, but not in door order numbers.
    assert submit(case, "ADDON", "direct").status_code == 200
    project_ids = []
    for index in range(10):
        project = ProjectORM(company_id=case.company, name="Same name", address=f"QA-{index}", status="OK")
        db_session.add(project)
        db_session.flush()
        door = DoorORM(company_id=case.company, project_id=project.id, door_type_id=case.door_type,
            installer_id=case.installer, unit_label=f"QA-{index}", status=DoorStatus.INSTALLED,
            order_number=f"ORDER-{index:02d}", our_price=500, version=0, is_locked=False)
        db_session.add(door)
        db_session.flush()
        db_session.add(CompletedWorkORM(company_id=case.company, project_id=project.id,
            installer_id=case.installer, work_kind="DOOR", door_id=door.id, quantity=1,
            rate_snapshot=250, amount_snapshot=250, completed_at=utcnow(), entry_type="ORIGINAL"))
        project_ids.append(str(project.id))
    db_session.commit()
    data = details(client_admin_real_uow, case.installer)
    assert data["project_rows_total"] == data["active_projects"] == 11
    assert data["order_rows_total"] == data["order_numbers"] == 10
    assert [row["project_id"] for row in data["top_projects"]] == sorted(project_ids)[:5]
    assert [row["order_number"] for row in data["order_breakdown"]] == [f"ORDER-{i:02d}" for i in range(8)]
    assert Decimal(data["payroll_total"]) == Decimal("2513.50")
    assert data == details(client_admin_real_uow, case.installer)


def test_foreign_metadata_never_leaks_and_missing_project_retains_earnings(case, client_admin_real_uow, db_session, make_installer):
    activate(case)
    assert submit(case, "DOOR", "install").status_code == 200
    foreign = CompanyORM(name="Private detail tenant")
    db_session.add(foreign)
    db_session.commit()
    installer = make_installer(company=foreign.id, full_name="Private performer")
    project = ProjectORM(company_id=foreign.id, name="Private detail site", address="QA", status="OK")
    db_session.add(project)
    db_session.commit()
    work = db_session.query(CompletedWorkORM).filter_by(company_id=case.company).one()
    db_session.get(DoorORM, case.door).status = DoorStatus.IN_PROGRESS
    try:
        for project_id in (project.id, None):
            work.project_id = project_id
            db_session.commit()
            data = details(client_admin_real_uow, case.installer)
            row = data["top_projects"][0]
            assert row["project_id"] is row["project_name"] is None
            assert data["active_projects"] == 0
            assert Decimal(row["payroll_total"]) == 250
            assert "Private" not in str(data)
        assert client_admin_real_uow.get(f"/api/v1/admin/reports/installers-kpi/{installer.id}").status_code == 404
    finally:
        work.project_id = case.project
        db_session.delete(project)
        db_session.delete(installer)
        db_session.delete(foreign)
        db_session.commit()


def test_installer_forbidden_and_invalid_confirmation_fails_closed(case, client_admin_real_uow, db_session):
    version, _ = activate(case)
    path = f"/api/v1/admin/reports/installers-kpi/{case.installer}"
    assert case.client.get(path).status_code == 403
    receipt = db_session.query(FactoryPriceApprovalORM).filter_by(price_list_id=version.id).one()
    receipt.snapshot_hash = "0" * 64
    db_session.commit()
    assert client_admin_real_uow.get(path).status_code == 409


def test_installer_directory_ties_have_stable_pages(case, client_admin_real_uow, make_installer):
    ids = sorted(str(make_installer(full_name="000 QA same name").id) for _ in range(3))
    actual = []
    for offset in range(3):
        response = client_admin_real_uow.get(f"/api/v1/admin/installers?limit=1&offset={offset}")
        assert response.status_code == 200, response.text
        actual.append(response.json()[0]["id"])
    assert actual == ids
