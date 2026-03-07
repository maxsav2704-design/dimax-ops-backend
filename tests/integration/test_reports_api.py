from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.modules.addons.domain.enums import AddonFactSource
from app.modules.addons.infrastructure.models import (
    AddonTypeORM,
    ProjectAddonFactORM,
    ProjectAddonPlanORM,
)
from app.modules.audit.infrastructure.models import AuditAlertReadCursorORM, AuditLogORM
from app.modules.calendar.domain.enums import CalendarEventType
from app.modules.calendar.infrastructure.models import (
    CalendarEventAssigneeORM,
    CalendarEventORM,
)
from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.issues.domain.enums import IssuePriority, IssueStatus, IssueWorkflowState
from app.modules.issues.infrastructure.models import IssueORM
from app.modules.outbox.domain.enums import DeliveryStatus, OutboxChannel, OutboxStatus
from app.modules.outbox.infrastructure.models import OutboxMessageORM
from app.modules.projects.domain.enums import ProjectStatus
from app.modules.projects.infrastructure.models import ProjectImportRunORM, ProjectORM
from app.modules.rates.infrastructure.models import InstallerRateORM
from app.modules.reasons.infrastructure.models import ReasonORM


def _seed_issue_report_row(db_session, *, company_id, make_door_type, unit_label: str):
    suffix = uuid.uuid4().hex[:8]
    project = ProjectORM(
        company_id=company_id,
        name=f"Issues Audit Project {suffix}",
        address=f"Issues Audit Address {suffix}",
        status=ProjectStatus.OK,
    )
    db_session.add(project)
    db_session.flush()

    door_type = make_door_type(name=f"Issues Audit Door {suffix}")
    door = DoorORM(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label=unit_label,
        our_price=Decimal("100.00"),
        status=DoorStatus.NOT_INSTALLED,
        installer_id=None,
        reason_id=None,
        comment=None,
        installed_at=None,
        is_locked=False,
    )
    db_session.add(door)
    db_session.flush()

    issue = IssueORM(
        company_id=company_id,
        door_id=door.id,
        status=IssueStatus.OPEN,
        workflow_state=IssueWorkflowState.NEW,
        priority=IssuePriority.P3,
        title=f"Issues audit {unit_label}",
        details=None,
        due_at=None,
    )
    db_session.add(issue)
    db_session.commit()
    return issue


def test_reports_kpi_returns_expected_shape(client_admin_real_uow):
    resp = client_admin_real_uow.get("/api/v1/admin/reports/kpi")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    for key in (
        "period_from",
        "period_to",
        "installed_doors",
        "not_installed_doors",
        "payroll_total",
        "revenue_total",
        "profit_total",
        "problem_projects",
        "missing_rates_installed_doors",
        "missing_addon_plans_done",
    ):
        assert key in body


def test_reports_dashboard_returns_expected_shape(client_admin_real_uow):
    resp = client_admin_real_uow.get("/api/v1/admin/reports/dashboard")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "kpi" in body
    assert "sync_health" in body
    assert "limits" in body
    assert isinstance(body["kpi"], dict)
    assert isinstance(body["sync_health"], dict)
    assert isinstance(body["limits"], dict)


def test_reports_dispatcher_board_returns_operational_snapshot(
    client_admin_real_uow,
    db_session,
    company_id,
    make_installer,
    make_door_type,
):
    suffix = uuid.uuid4().hex[:8]
    installer_available = make_installer(
        full_name=f"Dispatcher Alpha {suffix}",
        phone="+10000009001",
    )
    installer_busy = make_installer(
        full_name=f"Dispatcher Busy {suffix}",
        phone="+10000009002",
    )
    installer_busy.status = "BUSY"

    door_type = make_door_type(name=f"Dispatcher Door {suffix}")
    project = ProjectORM(
        company_id=company_id,
        name=f"Dispatcher Project {suffix}",
        address=f"Dispatcher Address {suffix}",
        contact_name="Eyal Cohen",
        status=ProjectStatus.PROBLEM,
    )
    db_session.add(project)
    db_session.flush()

    blocked_door = DoorORM(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label=f"BL-{suffix}",
        order_number="AZ-1001",
        our_price=Decimal("300.00"),
        status=DoorStatus.NOT_INSTALLED,
        installer_id=installer_busy.id,
        reason_id=None,
        comment=None,
        installed_at=None,
        is_locked=False,
    )
    unassigned_door = DoorORM(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label=f"UN-{suffix}",
        order_number="AZ-1001",
        our_price=Decimal("300.00"),
        status=DoorStatus.NOT_INSTALLED,
        installer_id=None,
        reason_id=None,
        comment=None,
        installed_at=None,
        is_locked=False,
    )
    installed_door = DoorORM(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label=f"IN-{suffix}",
        order_number="AZ-1001",
        our_price=Decimal("300.00"),
        status=DoorStatus.INSTALLED,
        installer_id=installer_available.id,
        reason_id=None,
        comment=None,
        installed_at=datetime.now(timezone.utc) - timedelta(days=1),
        is_locked=True,
    )
    db_session.add_all([blocked_door, unassigned_door, installed_door])
    db_session.flush()

    issue = IssueORM(
        company_id=company_id,
        door_id=blocked_door.id,
        status=IssueStatus.OPEN,
        workflow_state=IssueWorkflowState.BLOCKED,
        priority=IssuePriority.P1,
        title="Blocked opening",
        details="Client floor access not ready",
        due_at=None,
    )
    db_session.add(issue)
    db_session.flush()

    event = CalendarEventORM(
        company_id=company_id,
        title="Dispatcher Visit",
        event_type=CalendarEventType.INSTALLATION,
        starts_at=datetime.now(timezone.utc) + timedelta(days=1),
        ends_at=datetime.now(timezone.utc) + timedelta(days=1, hours=2),
        location="Ashdod Tower A",
        description=None,
        project_id=project.id,
    )
    db_session.add(event)
    db_session.flush()
    db_session.add(
        CalendarEventAssigneeORM(
            company_id=company_id,
            event_id=event.id,
            installer_id=installer_busy.id,
        )
    )
    db_session.commit()

    resp = client_admin_real_uow.get(
        "/api/v1/admin/reports/dispatcher-board?projects_limit=5&installers_limit=5&recommendation_limit=2"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["summary"]["total_projects"] >= 1
    assert body["summary"]["pending_doors"] >= 2
    assert body["summary"]["blocked_issues"] >= 1
    assert body["summary"]["unassigned_doors"] >= 1
    assert body["summary"]["scheduled_visits_7d"] >= 1

    project_row = next(
        item for item in body["projects"] if item["project_id"] == str(project.id)
    )
    assert project_row["dispatch_status"] == "BLOCKED"
    assert project_row["contact_name"] == "Eyal Cohen"
    assert project_row["pending_doors"] == 2
    assert project_row["unassigned_doors"] == 1
    assert project_row["blocked_issues"] == 1
    assert project_row["next_visit_title"] == "Dispatcher Visit"
    assert len(project_row["recommended_installers"]) == 2
    assert (
        project_row["recommended_installers"][0]["installer_id"]
        == str(installer_available.id)
    )

    installer_row = next(
        item
        for item in body["installers"]
        if item["installer_id"] == str(installer_busy.id)
    )
    assert installer_row["availability_band"] == "BUSY"
    assert installer_row["next_event_title"] == "Dispatcher Visit"


def test_reports_limits_returns_expected_shape(client_admin_real_uow):
    resp = client_admin_real_uow.get("/api/v1/admin/reports/limits")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    for key in (
        "plan_code",
        "plan_active",
        "total_doors",
        "users",
        "admin_users",
        "installer_users",
        "installers",
        "projects",
        "doors_per_project",
    ):
        assert key in body


def test_reports_problem_projects_returns_list_payload(client_admin_real_uow):
    resp = client_admin_real_uow.get("/api/v1/admin/reports/problem-projects")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "items" in body
    assert isinstance(body["items"], list)


def test_reports_top_reasons_returns_list_payload(client_admin_real_uow):
    resp = client_admin_real_uow.get("/api/v1/admin/reports/top-reasons")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "items" in body
    assert isinstance(body["items"], list)


def test_reports_installers_kpi_returns_expected_shape(client_admin_real_uow):
    resp = client_admin_real_uow.get("/api/v1/admin/reports/installers-kpi")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "period_from" in body
    assert "period_to" in body
    assert "items" in body
    assert isinstance(body["items"], list)


def test_reports_order_numbers_kpi_aggregates_by_order_number(
    client_admin_real_uow,
    db_session,
    company_id,
    make_installer,
    make_door_type,
):
    installer = make_installer(full_name="Order KPI Installer", phone="+10000000101")
    door_type = make_door_type(name="Order KPI Door")
    suffix = uuid.uuid4().hex[:8]

    project_a = ProjectORM(
        company_id=company_id,
        name=f"Order KPI A {suffix}",
        address=f"Order KPI A Street {suffix}",
        status=ProjectStatus.OK,
    )
    project_b = ProjectORM(
        company_id=company_id,
        name=f"Order KPI B {suffix}",
        address=f"Order KPI B Street {suffix}",
        status=ProjectStatus.OK,
    )
    db_session.add_all([project_a, project_b])
    db_session.flush()

    doors = [
        DoorORM(
            company_id=company_id,
            project_id=project_a.id,
            door_type_id=door_type.id,
            unit_label=f"ORD-{suffix}-1",
            order_number="AZ-100",
            our_price=Decimal("200.00"),
            status=DoorStatus.NOT_INSTALLED,
            installer_id=installer.id,
            reason_id=None,
            comment=None,
            installed_at=None,
            is_locked=False,
        ),
        DoorORM(
            company_id=company_id,
            project_id=project_a.id,
            door_type_id=door_type.id,
            unit_label=f"ORD-{suffix}-2",
            order_number="AZ-100",
            our_price=Decimal("120.00"),
            status=DoorStatus.NOT_INSTALLED,
            installer_id=installer.id,
            reason_id=None,
            comment=None,
            installed_at=None,
            is_locked=False,
        ),
        DoorORM(
            company_id=company_id,
            project_id=project_a.id,
            door_type_id=door_type.id,
            unit_label=f"ORD-{suffix}-3",
            order_number="AZ-200",
            our_price=Decimal("90.00"),
            status=DoorStatus.NOT_INSTALLED,
            installer_id=installer.id,
            reason_id=None,
            comment=None,
            installed_at=None,
            is_locked=False,
        ),
        DoorORM(
            company_id=company_id,
            project_id=project_b.id,
            door_type_id=door_type.id,
            unit_label=f"ORD-{suffix}-4",
            order_number="BZ-300",
            our_price=Decimal("80.00"),
            status=DoorStatus.NOT_INSTALLED,
            installer_id=installer.id,
            reason_id=None,
            comment=None,
            installed_at=None,
            is_locked=False,
        ),
    ]
    db_session.add_all(doors)
    db_session.commit()

    rate_resp = client_admin_real_uow.post(
        "/api/v1/admin/installer-rates",
        json={
            "installer_id": str(installer.id),
            "door_type_id": str(door_type.id),
            "price": "70.00",
        },
    )
    assert rate_resp.status_code == 201, rate_resp.text

    install_1 = client_admin_real_uow.post(f"/api/v1/admin/doors/{doors[0].id}/install")
    assert install_1.status_code == 200, install_1.text
    install_2 = client_admin_real_uow.post(f"/api/v1/admin/doors/{doors[2].id}/install")
    assert install_2.status_code == 200, install_2.text

    issue = IssueORM(
        company_id=company_id,
        door_id=doors[1].id,
        status=IssueStatus.OPEN,
        workflow_state=IssueWorkflowState.NEW,
        priority=IssuePriority.P3,
        title="Open issue for AZ-100",
        details=None,
        due_at=None,
    )
    db_session.add(issue)
    db_session.commit()

    resp = client_admin_real_uow.get("/api/v1/admin/reports/order-numbers-kpi")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] >= 3
    assert body["limit"] == 200
    assert body["offset"] == 0
    by_order = {x["order_number"]: x for x in body["items"]}

    assert "AZ-100" in by_order
    az100 = by_order["AZ-100"]
    assert az100["total_doors"] == 2
    assert az100["installed_doors"] == 1
    assert az100["not_installed_doors"] == 1
    assert az100["open_issues"] == 1
    assert Decimal(str(az100["planned_revenue_total"])) == Decimal("320.00")
    assert Decimal(str(az100["installed_revenue_total"])) == Decimal("200.00")
    assert Decimal(str(az100["payroll_total"])) == Decimal("70.00")
    assert Decimal(str(az100["profit_total"])) == Decimal("130.00")
    assert az100["missing_rates_installed_doors"] == 0
    assert az100["completion_pct"] == 50.0

    filtered = client_admin_real_uow.get(
        f"/api/v1/admin/reports/order-numbers-kpi?project_id={project_a.id}&q=az-"
    )
    assert filtered.status_code == 200, filtered.text
    filtered_body = filtered.json()
    filtered_orders = [x["order_number"] for x in filtered_body["items"]]
    assert "AZ-100" in filtered_orders
    assert "AZ-200" in filtered_orders
    assert "BZ-300" not in filtered_orders
    sorted_by_revenue = client_admin_real_uow.get(
        f"/api/v1/admin/reports/order-numbers-kpi?project_id={project_a.id}&sort_by=planned_revenue_total&sort_dir=asc"
    )
    assert sorted_by_revenue.status_code == 200, sorted_by_revenue.text
    sorted_items = sorted_by_revenue.json()["items"]
    sorted_orders = [x["order_number"] for x in sorted_items]
    assert sorted_orders.index("AZ-200") < sorted_orders.index("AZ-100")

    export_resp = client_admin_real_uow.get(
        f"/api/v1/admin/reports/order-numbers-kpi/export?project_id={project_a.id}&q=az-&sort_by=planned_revenue_total&sort_dir=asc"
    )
    assert export_resp.status_code == 200, export_resp.text
    assert export_resp.headers["content-type"].startswith("text/csv")
    assert "attachment;" in export_resp.headers["content-disposition"]
    csv_body = export_resp.text
    assert (
        "order_number,total_doors,installed_doors,not_installed_doors,open_issues,"
        "planned_revenue_total,installed_revenue_total,payroll_total,profit_total,"
        "missing_rates_installed_doors,completion_pct"
    ) in csv_body
    assert "AZ-100" in csv_body
    assert "AZ-200" in csv_body
    assert "BZ-300" not in csv_body


def test_reports_installers_kpi_aggregates_money_by_installer(
    client_admin_real_uow,
    db_session,
    company_id,
    make_installer,
    make_door_type,
):
    installer_a = make_installer(full_name="KPI Installer A", phone="+10000000029")
    installer_b = make_installer(full_name="KPI Installer B", phone="+10000000030")
    door_type = make_door_type(name="KPI Door")
    suffix = uuid.uuid4().hex[:8]
    project = ProjectORM(
        company_id=company_id,
        name=f"KPI Project {suffix}",
        address=f"KPI Street {suffix}",
        status=ProjectStatus.OK,
    )
    db_session.add(project)
    db_session.flush()

    doors = [
        DoorORM(
            company_id=company_id,
            project_id=project.id,
            door_type_id=door_type.id,
            unit_label=f"KPI-A-{suffix}-1",
            our_price=Decimal("200.00"),
            status=DoorStatus.NOT_INSTALLED,
            installer_id=installer_a.id,
            reason_id=None,
            comment=None,
            installed_at=None,
            is_locked=False,
        ),
        DoorORM(
            company_id=company_id,
            project_id=project.id,
            door_type_id=door_type.id,
            unit_label=f"KPI-A-{suffix}-2",
            our_price=Decimal("200.00"),
            status=DoorStatus.NOT_INSTALLED,
            installer_id=installer_a.id,
            reason_id=None,
            comment=None,
            installed_at=None,
            is_locked=False,
        ),
        DoorORM(
            company_id=company_id,
            project_id=project.id,
            door_type_id=door_type.id,
            unit_label=f"KPI-B-{suffix}-1",
            our_price=Decimal("220.00"),
            status=DoorStatus.NOT_INSTALLED,
            installer_id=installer_b.id,
            reason_id=None,
            comment=None,
            installed_at=None,
            is_locked=False,
        ),
    ]
    db_session.add_all(doors)
    db_session.commit()

    rate_a = client_admin_real_uow.post(
        "/api/v1/admin/installer-rates",
        json={
            "installer_id": str(installer_a.id),
            "door_type_id": str(door_type.id),
            "price": "120.00",
        },
    )
    assert rate_a.status_code == 201, rate_a.text
    rate_b = client_admin_real_uow.post(
        "/api/v1/admin/installer-rates",
        json={
            "installer_id": str(installer_b.id),
            "door_type_id": str(door_type.id),
            "price": "150.00",
        },
    )
    assert rate_b.status_code == 201, rate_b.text

    for door in doors:
        install_resp = client_admin_real_uow.post(f"/api/v1/admin/doors/{door.id}/install")
        assert install_resp.status_code == 200, install_resp.text

    resp = client_admin_real_uow.get("/api/v1/admin/reports/installers-kpi")
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    by_name = {x["installer_name"]: x for x in items}
    assert "KPI Installer A" in by_name
    assert "KPI Installer B" in by_name

    a = by_name["KPI Installer A"]
    assert a["installed_doors"] == 2
    assert Decimal(str(a["revenue_total"])) == Decimal("400.00")
    assert Decimal(str(a["payroll_total"])) == Decimal("240.00")
    assert Decimal(str(a["profit_total"])) == Decimal("160.00")
    assert a["missing_rates_installed_doors"] == 0

    b = by_name["KPI Installer B"]
    assert b["installed_doors"] == 1
    assert Decimal(str(b["revenue_total"])) == Decimal("220.00")
    assert Decimal(str(b["payroll_total"])) == Decimal("150.00")
    assert Decimal(str(b["profit_total"])) == Decimal("70.00")
    assert b["missing_rates_installed_doors"] == 0
    sorted_resp = client_admin_real_uow.get(
        "/api/v1/admin/reports/installers-kpi?sort_by=payroll_total&sort_dir=asc"
    )
    assert sorted_resp.status_code == 200, sorted_resp.text
    sorted_names = [x["installer_name"] for x in sorted_resp.json()["items"]]
    assert sorted_names.index("KPI Installer B") < sorted_names.index("KPI Installer A")

    export_resp = client_admin_real_uow.get(
        "/api/v1/admin/reports/installers-kpi/export?sort_by=payroll_total&sort_dir=asc"
    )
    assert export_resp.status_code == 200, export_resp.text
    assert export_resp.headers["content-type"].startswith("text/csv")
    assert "attachment;" in export_resp.headers["content-disposition"]
    csv_body = export_resp.text
    assert (
        "installer_id,installer_name,installed_doors,payroll_total,revenue_total,"
        "profit_total,missing_rates_installed_doors"
    ) in csv_body
    assert "KPI Installer A" in csv_body
    assert "KPI Installer B" in csv_body


def test_reports_installer_profitability_matrix_returns_ranked_rows(
    client_admin_real_uow,
    db_session,
    company_id,
    make_installer,
    make_door_type,
):
    installer_strong = make_installer(full_name="Matrix Strong", phone="+10000001010")
    installer_risk = make_installer(full_name="Matrix Risk", phone="+10000001011")
    door_type = make_door_type(name="Matrix Door")
    now = datetime.now(timezone.utc)
    suffix = uuid.uuid4().hex[:8]

    project_a = ProjectORM(
        company_id=company_id,
        name=f"Matrix A {suffix}",
        address=f"Matrix Street A {suffix}",
        status=ProjectStatus.OK,
    )
    project_b = ProjectORM(
        company_id=company_id,
        name=f"Matrix B {suffix}",
        address=f"Matrix Street B {suffix}",
        status=ProjectStatus.PROBLEM,
    )
    db_session.add_all([project_a, project_b])
    db_session.flush()

    db_session.add_all(
        [
            InstallerRateORM(
                company_id=company_id,
                installer_id=installer_strong.id,
                door_type_id=door_type.id,
                effective_from=now,
                price=Decimal("100.00"),
            ),
            InstallerRateORM(
                company_id=company_id,
                installer_id=installer_risk.id,
                door_type_id=door_type.id,
                effective_from=now,
                price=Decimal("140.00"),
            ),
        ]
    )
    db_session.flush()

    strong_doors = [
        DoorORM(
            company_id=company_id,
            project_id=project_a.id,
            door_type_id=door_type.id,
            unit_label=f"MX-S-{suffix}-1",
            our_price=Decimal("300.00"),
            status=DoorStatus.INSTALLED,
            installer_id=installer_strong.id,
            installer_rate_snapshot=Decimal("100.00"),
            reason_id=None,
            comment=None,
            installed_at=now - timedelta(days=1),
            is_locked=False,
        ),
        DoorORM(
            company_id=company_id,
            project_id=project_a.id,
            door_type_id=door_type.id,
            unit_label=f"MX-S-{suffix}-2",
            our_price=Decimal("280.00"),
            status=DoorStatus.INSTALLED,
            installer_id=installer_strong.id,
            installer_rate_snapshot=Decimal("100.00"),
            reason_id=None,
            comment=None,
            installed_at=now,
            is_locked=False,
        ),
    ]
    risk_doors = [
        DoorORM(
            company_id=company_id,
            project_id=project_b.id,
            door_type_id=door_type.id,
            unit_label=f"MX-R-{suffix}-1",
            our_price=Decimal("150.00"),
            status=DoorStatus.INSTALLED,
            installer_id=installer_risk.id,
            installer_rate_snapshot=Decimal("140.00"),
            reason_id=None,
            comment=None,
            installed_at=now,
            is_locked=False,
        ),
        DoorORM(
            company_id=company_id,
            project_id=project_b.id,
            door_type_id=door_type.id,
            unit_label=f"MX-R-{suffix}-2",
            our_price=Decimal("150.00"),
            status=DoorStatus.NOT_INSTALLED,
            installer_id=installer_risk.id,
            reason_id=None,
            comment=None,
            installed_at=None,
            is_locked=False,
        ),
    ]
    db_session.add_all(strong_doors + risk_doors)
    db_session.flush()

    db_session.add_all(
        [
            IssueORM(
                company_id=company_id,
                door_id=risk_doors[0].id,
                status=IssueStatus.OPEN,
                workflow_state=IssueWorkflowState.BLOCKED,
                priority=IssuePriority.P1,
                title="Risk installer issue",
                details=None,
                due_at=now,
            ),
            IssueORM(
                company_id=company_id,
                door_id=risk_doors[1].id,
                status=IssueStatus.OPEN,
                workflow_state=IssueWorkflowState.NEW,
                priority=IssuePriority.P2,
                title="Waiting install",
                details=None,
                due_at=now,
            ),
        ]
    )

    addon_type = AddonTypeORM(
        company_id=company_id,
        name=f"Matrix Addon {suffix}",
        unit="pcs",
        default_client_price=Decimal("15.00"),
        default_installer_price=Decimal("6.00"),
        is_active=True,
    )
    db_session.add(addon_type)
    db_session.flush()

    db_session.add(
        ProjectAddonPlanORM(
            company_id=company_id,
            project_id=project_a.id,
            addon_type_id=addon_type.id,
            qty_planned=Decimal("4.00"),
            client_price=Decimal("15.00"),
            installer_price=Decimal("6.00"),
        )
    )
    db_session.add(
        ProjectAddonFactORM(
            company_id=company_id,
            project_id=project_a.id,
            addon_type_id=addon_type.id,
            installer_id=installer_strong.id,
            qty_done=Decimal("3.00"),
            done_at=now,
            comment=None,
            source=AddonFactSource.ONLINE,
            client_event_id=None,
        )
    )
    db_session.commit()

    top_resp = client_admin_real_uow.get(
        "/api/v1/admin/reports/installers-profitability-matrix"
        "?limit=5&sort_by=profit_total&sort_dir=desc"
    )
    assert top_resp.status_code == 200, top_resp.text
    top_body = top_resp.json()
    assert top_body["total"] >= 2
    assert top_body["items"][0]["installer_name"] == "Matrix Strong"
    assert top_body["items"][0]["performance_band"] == "STRONG"
    assert Decimal(str(top_body["items"][0]["profit_total"])) == Decimal("407.00")
    assert Decimal(str(top_body["items"][0]["avg_profit_per_door"])) == Decimal("203.50")

    risk_resp = client_admin_real_uow.get(
        "/api/v1/admin/reports/installers-profitability-matrix"
        "?limit=5&sort_by=profit_total&sort_dir=asc"
    )
    assert risk_resp.status_code == 200, risk_resp.text
    risk_body = risk_resp.json()
    assert risk_body["items"][0]["installer_name"] == "Matrix Risk"
    assert risk_body["items"][0]["performance_band"] == "RISK"
    assert Decimal(str(risk_body["items"][0]["profit_total"])) == Decimal("10.00")
    assert risk_body["items"][0]["open_issues"] == 2


def test_reports_installer_project_profitability_returns_cross_view_rows(
    client_admin_real_uow,
    db_session,
    company_id,
    make_installer,
    make_door_type,
):
    now = datetime.now(timezone.utc)
    installer_a = make_installer(full_name="Cross Alpha", phone="+10000001020")
    installer_b = make_installer(full_name="Cross Beta", phone="+10000001021")
    door_type = make_door_type(name="Cross Door")
    suffix = uuid.uuid4().hex[:8]

    project_top = ProjectORM(
        company_id=company_id,
        name=f"Cross Tower A {suffix}",
        address=f"Cross Street A {suffix}",
        status=ProjectStatus.OK,
    )
    project_risk = ProjectORM(
        company_id=company_id,
        name=f"Cross Tower B {suffix}",
        address=f"Cross Street B {suffix}",
        status=ProjectStatus.PROBLEM,
    )
    db_session.add_all([project_top, project_risk])
    db_session.flush()

    db_session.add_all(
        [
            InstallerRateORM(
                company_id=company_id,
                installer_id=installer_a.id,
                door_type_id=door_type.id,
                effective_from=now,
                price=Decimal("90.00"),
            ),
            InstallerRateORM(
                company_id=company_id,
                installer_id=installer_b.id,
                door_type_id=door_type.id,
                effective_from=now,
                price=Decimal("130.00"),
            ),
        ]
    )
    db_session.flush()

    door_a1 = DoorORM(
        company_id=company_id,
        project_id=project_top.id,
        door_type_id=door_type.id,
        unit_label=f"CP-A-{suffix}-1",
        our_price=Decimal("250.00"),
        status=DoorStatus.INSTALLED,
        installer_id=installer_a.id,
        installer_rate_snapshot=Decimal("90.00"),
        reason_id=None,
        comment=None,
        installed_at=now - timedelta(days=1),
        is_locked=False,
    )
    door_a2 = DoorORM(
        company_id=company_id,
        project_id=project_top.id,
        door_type_id=door_type.id,
        unit_label=f"CP-A-{suffix}-2",
        our_price=Decimal("220.00"),
        status=DoorStatus.INSTALLED,
        installer_id=installer_a.id,
        installer_rate_snapshot=Decimal("90.00"),
        reason_id=None,
        comment=None,
        installed_at=now,
        is_locked=False,
    )
    door_b1 = DoorORM(
        company_id=company_id,
        project_id=project_risk.id,
        door_type_id=door_type.id,
        unit_label=f"CP-B-{suffix}-1",
        our_price=Decimal("150.00"),
        status=DoorStatus.INSTALLED,
        installer_id=installer_b.id,
        installer_rate_snapshot=Decimal("130.00"),
        reason_id=None,
        comment=None,
        installed_at=now,
        is_locked=False,
    )
    db_session.add_all([door_a1, door_a2, door_b1])
    db_session.flush()

    db_session.add(
        IssueORM(
            company_id=company_id,
            door_id=door_b1.id,
            status=IssueStatus.OPEN,
            workflow_state=IssueWorkflowState.BLOCKED,
            priority=IssuePriority.P1,
            title="Cross risk issue",
            details=None,
            due_at=now,
        )
    )

    addon_type = AddonTypeORM(
        company_id=company_id,
        name=f"Cross Addon {suffix}",
        unit="pcs",
        default_client_price=Decimal("20.00"),
        default_installer_price=Decimal("8.00"),
        is_active=True,
    )
    db_session.add(addon_type)
    db_session.flush()

    db_session.add(
        ProjectAddonPlanORM(
            company_id=company_id,
            project_id=project_top.id,
            addon_type_id=addon_type.id,
            qty_planned=Decimal("3.00"),
            client_price=Decimal("20.00"),
            installer_price=Decimal("8.00"),
        )
    )
    db_session.add(
        ProjectAddonFactORM(
            company_id=company_id,
            project_id=project_top.id,
            addon_type_id=addon_type.id,
            installer_id=installer_a.id,
            qty_done=Decimal("2.00"),
            done_at=now,
            comment=None,
            source=AddonFactSource.ONLINE,
            client_event_id=None,
        )
    )
    db_session.commit()

    top_resp = client_admin_real_uow.get(
        "/api/v1/admin/reports/installer-project-profitability"
        "?limit=10&sort_by=profit_total&sort_dir=desc"
    )
    assert top_resp.status_code == 200, top_resp.text
    top_body = top_resp.json()
    assert top_body["total"] >= 2
    assert top_body["items"][0]["installer_name"] == "Cross Alpha"
    assert top_body["items"][0]["project_name"].startswith("Cross Tower A ")
    assert top_body["items"][0]["performance_band"] == "STRONG"
    assert Decimal(str(top_body["items"][0]["profit_total"])) == Decimal("314.00")

    risk_resp = client_admin_real_uow.get(
        "/api/v1/admin/reports/installer-project-profitability"
        "?limit=10&sort_by=profit_total&sort_dir=asc"
    )
    assert risk_resp.status_code == 200, risk_resp.text
    risk_body = risk_resp.json()
    assert risk_body["items"][0]["installer_name"] == "Cross Beta"
    assert risk_body["items"][0]["project_name"].startswith("Cross Tower B ")
    assert risk_body["items"][0]["performance_band"] == "RISK"
    assert Decimal(str(risk_body["items"][0]["profit_total"])) == Decimal("20.00")
    assert risk_body["items"][0]["open_issues"] == 1


def test_reports_risk_concentration_returns_executive_risk_views(
    client_admin_real_uow,
    db_session,
    company_id,
    make_installer,
    make_door_type,
    make_reason,
):
    now = datetime.now(timezone.utc)
    suffix = uuid.uuid4().hex[:8]
    installer_risk = make_installer(full_name="Risk Focus", phone="+10000001030")
    installer_ok = make_installer(full_name="Risk Stable", phone="+10000001031")
    reason_blocked = make_reason(name="Risk Blocked")
    door_type = make_door_type(name="Risk Concentration Door")

    project_risk = ProjectORM(
        company_id=company_id,
        name=f"Risk Tower {suffix}",
        address=f"Risk Street {suffix}",
        status=ProjectStatus.PROBLEM,
    )
    project_ok = ProjectORM(
        company_id=company_id,
        name=f"Stable Tower {suffix}",
        address=f"Stable Street {suffix}",
        status=ProjectStatus.OK,
    )
    db_session.add_all([project_risk, project_ok])
    db_session.flush()

    db_session.add_all(
        [
            InstallerRateORM(
                company_id=company_id,
                installer_id=installer_risk.id,
                door_type_id=door_type.id,
                effective_from=now,
                price=Decimal("60.00"),
            ),
            InstallerRateORM(
                company_id=company_id,
                installer_id=installer_ok.id,
                door_type_id=door_type.id,
                effective_from=now,
                price=Decimal("80.00"),
            ),
        ]
    )
    db_session.flush()

    delayed_door = DoorORM(
        company_id=company_id,
        project_id=project_risk.id,
        door_type_id=door_type.id,
        unit_label=f"RC-{suffix}-DELAY",
        order_number="RC-100",
        our_price=Decimal("180.00"),
        status=DoorStatus.NOT_INSTALLED,
        installer_id=installer_risk.id,
        reason_id=reason_blocked.id,
        comment=None,
        installed_at=None,
        is_locked=False,
    )
    risk_installed = DoorORM(
        company_id=company_id,
        project_id=project_risk.id,
        door_type_id=door_type.id,
        unit_label=f"RC-{suffix}-LIVE",
        order_number="RC-100",
        our_price=Decimal("140.00"),
        status=DoorStatus.INSTALLED,
        installer_id=installer_risk.id,
        installer_rate_snapshot=Decimal("120.00"),
        reason_id=None,
        comment=None,
        installed_at=now,
        is_locked=False,
    )
    stable_installed = DoorORM(
        company_id=company_id,
        project_id=project_ok.id,
        door_type_id=door_type.id,
        unit_label=f"RC-{suffix}-OK",
        order_number="RC-200",
        our_price=Decimal("300.00"),
        status=DoorStatus.INSTALLED,
        installer_id=installer_ok.id,
        installer_rate_snapshot=Decimal("80.00"),
        reason_id=None,
        comment=None,
        installed_at=now,
        is_locked=False,
    )
    db_session.add_all([delayed_door, risk_installed, stable_installed])
    db_session.flush()

    db_session.add(
        IssueORM(
            company_id=company_id,
            door_id=risk_installed.id,
            status=IssueStatus.OPEN,
            workflow_state=IssueWorkflowState.BLOCKED,
            priority=IssuePriority.P1,
            title="Risk concentration issue",
            details=None,
            due_at=now,
        )
    )
    db_session.commit()

    resp = client_admin_real_uow.get("/api/v1/admin/reports/risk-concentration?limit=3")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["summary"]["risky_projects"] >= 1
    assert body["summary"]["risky_orders"] >= 1
    assert body["summary"]["risky_installers"] >= 1
    assert Decimal(str(body["summary"]["delayed_profit_total"])) == Decimal("120.00")
    assert Decimal(str(body["summary"]["blocked_issue_profit_at_risk"])) == Decimal("20.00")
    assert Decimal(str(body["summary"]["worst_project_profit_total"])) == Decimal("20.00")
    assert Decimal(str(body["summary"]["worst_order_profit_total"])) == Decimal("20.00")
    assert Decimal(str(body["summary"]["worst_installer_profit_total"])) == Decimal("20.00")
    assert body["projects"][0]["project_name"].startswith("Risk Tower ")
    assert body["orders"][0]["order_number"] == "RC-100"
    assert body["installers"][0]["installer_name"] == "Risk Focus"


def test_reports_executive_export_returns_csv_snapshot(
    client_admin_real_uow,
    db_session,
    company_id,
):
    project = ProjectORM(
        company_id=company_id,
        name=f"Executive Export {uuid.uuid4().hex[:8]}",
        address="Executive Export Street",
        status=ProjectStatus.OK,
    )
    db_session.add(project)
    db_session.commit()

    resp = client_admin_real_uow.get(
        f"/api/v1/admin/reports/executive/export?project_plan_fact_project_id={project.id}"
        f"&project_risk_project_id={project.id}"
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment;" in resp.headers["content-disposition"]
    body = resp.text
    assert "section,metric,value_1,value_2,value_3,value_4" in body
    assert "executive_summary,risk_concentration" in body
    assert "project_plan_fact" in body
    assert "project_risk_drilldown" in body


def test_reports_installer_kpi_details_returns_expected_metrics(
    client_admin_real_uow,
    db_session,
    company_id,
    make_installer,
    make_door_type,
):
    installer = make_installer(full_name="Details Installer", phone="+10000000991")
    door_type = make_door_type(name="Details Door")
    suffix = uuid.uuid4().hex[:8]
    project_a = ProjectORM(
        company_id=company_id,
        name=f"Details Project A {suffix}",
        address=f"Details Street A {suffix}",
        status=ProjectStatus.OK,
    )
    project_b = ProjectORM(
        company_id=company_id,
        name=f"Details Project B {suffix}",
        address=f"Details Street B {suffix}",
        status=ProjectStatus.OK,
    )
    db_session.add_all([project_a, project_b])
    db_session.flush()

    rate = InstallerRateORM(
        company_id=company_id,
        installer_id=installer.id,
        door_type_id=door_type.id,
        effective_from=datetime.now(timezone.utc),
        price=Decimal("120.00"),
    )
    db_session.add(rate)

    door_1 = DoorORM(
        company_id=company_id,
        project_id=project_a.id,
        door_type_id=door_type.id,
        unit_label=f"DET-{suffix}-1",
        order_number="AZ-901",
        our_price=Decimal("200.00"),
        status=DoorStatus.INSTALLED,
        installer_id=installer.id,
        installer_rate_snapshot=Decimal("100.00"),
        reason_id=None,
        comment=None,
        installed_at=datetime.now(timezone.utc) - timedelta(days=1),
        is_locked=False,
    )
    door_2 = DoorORM(
        company_id=company_id,
        project_id=project_b.id,
        door_type_id=door_type.id,
        unit_label=f"DET-{suffix}-2",
        order_number="AZ-902",
        our_price=Decimal("300.00"),
        status=DoorStatus.INSTALLED,
        installer_id=installer.id,
        installer_rate_snapshot=None,
        reason_id=None,
        comment=None,
        installed_at=datetime.now(timezone.utc),
        is_locked=False,
    )
    db_session.add_all([door_1, door_2])
    db_session.flush()

    db_session.add(
        IssueORM(
            company_id=company_id,
            door_id=door_2.id,
            status=IssueStatus.OPEN,
            workflow_state=IssueWorkflowState.NEW,
            priority=IssuePriority.P2,
            title="Installer details issue",
            details=None,
            due_at=None,
        )
    )

    addon_type = AddonTypeORM(
        company_id=company_id,
        name=f"Installer Addon {suffix}",
        unit="pcs",
        default_client_price=Decimal("12.00"),
        default_installer_price=Decimal("5.00"),
        is_active=True,
    )
    db_session.add(addon_type)
    db_session.flush()

    db_session.add(
        ProjectAddonPlanORM(
            company_id=company_id,
            project_id=project_a.id,
            addon_type_id=addon_type.id,
            qty_planned=Decimal("4.00"),
            client_price=Decimal("12.00"),
            installer_price=Decimal("5.00"),
        )
    )
    db_session.add(
        ProjectAddonFactORM(
            company_id=company_id,
            project_id=project_a.id,
            addon_type_id=addon_type.id,
            installer_id=installer.id,
            qty_done=Decimal("2.00"),
            done_at=datetime.now(timezone.utc),
            comment=None,
            source=AddonFactSource.ONLINE,
            client_event_id=None,
        )
    )
    db_session.commit()

    resp = client_admin_real_uow.get(
        f"/api/v1/admin/reports/installers-kpi/{installer.id}"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["installer_id"] == str(installer.id)
    assert body["installer_name"] == "Details Installer"
    assert body["installed_doors"] == 2
    assert body["active_projects"] == 2
    assert body["order_numbers"] == 2
    assert body["open_issues"] == 1
    assert Decimal(str(body["addons_done_qty"])) == Decimal("2.00")
    assert Decimal(str(body["addon_revenue_total"])) == Decimal("24.00")
    assert Decimal(str(body["addon_payroll_total"])) == Decimal("10.00")
    assert Decimal(str(body["addon_profit_total"])) == Decimal("14.00")
    assert Decimal(str(body["revenue_total"])) == Decimal("524.00")
    assert Decimal(str(body["payroll_total"])) == Decimal("230.00")
    assert Decimal(str(body["profit_total"])) == Decimal("294.00")
    assert body["missing_rates_installed_doors"] == 0
    assert body["missing_addon_plans_facts"] == 0
    assert len(body["top_projects"]) == 2
    assert len(body["order_breakdown"]) == 2
    assert {item["order_number"] for item in body["order_breakdown"]} == {"AZ-901", "AZ-902"}


def test_reports_top_reasons_respects_date_period(
    client_admin_real_uow,
    db_session,
    company_id,
    make_door_type,
):
    project = ProjectORM(
        company_id=company_id,
        name="Top Reasons Period Project",
        address="Top Reasons Address",
        status=ProjectStatus.OK,
    )
    db_session.add(project)
    db_session.flush()

    reason_old = ReasonORM(
        company_id=company_id,
        code=f"old-{uuid.uuid4().hex[:6]}",
        name="Old Reason",
        is_active=True,
    )
    reason_new = ReasonORM(
        company_id=company_id,
        code=f"new-{uuid.uuid4().hex[:6]}",
        name="New Reason",
        is_active=True,
    )
    db_session.add_all([reason_old, reason_new])
    db_session.flush()

    door_type = make_door_type(name="Top Reasons Door")

    old_door = DoorORM(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label="R-OLD",
        our_price=Decimal("100.00"),
        status=DoorStatus.NOT_INSTALLED,
        installer_id=None,
        reason_id=reason_old.id,
        comment=None,
        installed_at=None,
        is_locked=False,
    )
    new_door = DoorORM(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label="R-NEW",
        our_price=Decimal("100.00"),
        status=DoorStatus.NOT_INSTALLED,
        installer_id=None,
        reason_id=reason_new.id,
        comment=None,
        installed_at=None,
        is_locked=False,
    )
    db_session.add_all([old_door, new_door])
    db_session.flush()

    now = datetime.now(timezone.utc)
    old_door.updated_at = now - timedelta(days=5)
    new_door.updated_at = now
    db_session.add_all([old_door, new_door])
    db_session.commit()

    date_from = (now - timedelta(days=1)).isoformat()
    date_to = (now + timedelta(days=1)).isoformat()
    resp = client_admin_real_uow.get(
        "/api/v1/admin/reports/top-reasons",
        params={"date_from": date_from, "date_to": date_to},
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert any(x["reason_name"] == "New Reason" for x in items)
    assert all(x["reason_name"] != "Old Reason" for x in items)


def test_reports_delivery_returns_expected_shape(client_admin_real_uow):
    resp = client_admin_real_uow.get("/api/v1/admin/reports/delivery")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    for key in (
        "period_from",
        "period_to",
        "whatsapp_pending",
        "whatsapp_delivered",
        "whatsapp_failed",
        "email_sent",
        "email_failed",
    ):
        assert key in body


def test_reports_project_profit_not_found_returns_404(client_admin_real_uow):
    resp = client_admin_real_uow.get(
        f"/api/v1/admin/reports/project-profit/{uuid.uuid4()}"
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_reports_project_profit_existing_project_returns_payload(
    client_admin_real_uow,
):
    create_resp = client_admin_real_uow.post(
        "/api/v1/admin/projects",
        json={
            "name": "Reports Project",
            "address": "Reports Street 1",
        },
    )
    assert create_resp.status_code == 200, create_resp.text
    project_id = create_resp.json()["id"]

    profit_resp = client_admin_real_uow.get(
        f"/api/v1/admin/reports/project-profit/{project_id}"
    )
    assert profit_resp.status_code == 200, profit_resp.text
    body = profit_resp.json()
    assert body["project_id"] == project_id
    for key in (
        "installed_doors",
        "payroll_total",
        "revenue_total",
        "profit_total",
        "missing_rates_installed_doors",
    ):
        assert key in body


def test_reports_project_plan_fact_not_found_returns_404(client_admin_real_uow):
    resp = client_admin_real_uow.get(
        f"/api/v1/admin/reports/project-plan-fact/{uuid.uuid4()}"
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_reports_project_plan_fact_returns_expected_metrics(
    client_admin_real_uow,
    db_session,
    company_id,
    make_installer,
    make_door_type,
):
    installer = make_installer(full_name="Plan Fact Installer")
    door_type = make_door_type(name="Plan Fact Door")
    suffix = uuid.uuid4().hex[:8]
    project = ProjectORM(
        company_id=company_id,
        name=f"Plan Fact Project {suffix}",
        address=f"Plan Fact Address {suffix}",
        status=ProjectStatus.OK,
    )
    db_session.add(project)
    db_session.flush()

    rate = InstallerRateORM(
        company_id=company_id,
        installer_id=installer.id,
        door_type_id=door_type.id,
        effective_from=datetime.now(timezone.utc),
        price=Decimal("120.00"),
    )
    db_session.add(rate)

    door_installed = DoorORM(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label=f"PF-INST-{suffix}",
        our_price=Decimal("200.00"),
        status=DoorStatus.INSTALLED,
        installer_id=installer.id,
        installer_rate_snapshot=Decimal("80.00"),
        reason_id=None,
        comment=None,
        installed_at=datetime.now(timezone.utc),
        is_locked=False,
    )
    door_not_installed = DoorORM(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label=f"PF-PLAN-{suffix}",
        our_price=Decimal("300.00"),
        status=DoorStatus.NOT_INSTALLED,
        installer_id=installer.id,
        installer_rate_snapshot=None,
        reason_id=None,
        comment=None,
        installed_at=None,
        is_locked=False,
    )
    db_session.add_all([door_installed, door_not_installed])
    db_session.flush()

    open_issue = IssueORM(
        company_id=company_id,
        door_id=door_installed.id,
        status=IssueStatus.OPEN,
        workflow_state=IssueWorkflowState.NEW,
        priority=IssuePriority.P2,
        title=f"Plan fact issue {suffix}",
        details=None,
        due_at=None,
    )
    db_session.add(open_issue)

    addon_type = AddonTypeORM(
        company_id=company_id,
        name=f"Addon {suffix}",
        unit="pcs",
        default_client_price=Decimal("10.00"),
        default_installer_price=Decimal("4.00"),
        is_active=True,
    )
    db_session.add(addon_type)
    db_session.flush()

    addon_plan = ProjectAddonPlanORM(
        company_id=company_id,
        project_id=project.id,
        addon_type_id=addon_type.id,
        qty_planned=Decimal("5.00"),
        client_price=Decimal("10.00"),
        installer_price=Decimal("4.00"),
    )
    addon_fact = ProjectAddonFactORM(
        company_id=company_id,
        project_id=project.id,
        addon_type_id=addon_type.id,
        installer_id=installer.id,
        qty_done=Decimal("2.00"),
        done_at=datetime.now(timezone.utc),
        comment=None,
        source=AddonFactSource.ONLINE,
        client_event_id=None,
    )
    db_session.add_all([addon_plan, addon_fact])
    db_session.commit()

    resp = client_admin_real_uow.get(
        f"/api/v1/admin/reports/project-plan-fact/{project.id}"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["project_id"] == str(project.id)
    assert body["total_doors"] == 2
    assert body["installed_doors"] == 1
    assert body["not_installed_doors"] == 1
    assert body["completion_pct"] == 50.0
    assert body["open_issues"] == 1
    assert Decimal(str(body["planned_revenue_total"])) == Decimal("550.00")
    assert Decimal(str(body["actual_revenue_total"])) == Decimal("220.00")
    assert Decimal(str(body["revenue_gap_total"])) == Decimal("330.00")
    assert Decimal(str(body["planned_payroll_total"])) == Decimal("220.00")
    assert Decimal(str(body["actual_payroll_total"])) == Decimal("88.00")
    assert Decimal(str(body["payroll_gap_total"])) == Decimal("132.00")
    assert Decimal(str(body["planned_profit_total"])) == Decimal("330.00")
    assert Decimal(str(body["actual_profit_total"])) == Decimal("132.00")
    assert Decimal(str(body["profit_gap_total"])) == Decimal("198.00")
    assert Decimal(str(body["planned_addons_qty"])) == Decimal("5.00")
    assert Decimal(str(body["actual_addons_qty"])) == Decimal("2.00")
    assert body["missing_planned_rates_doors"] == 0
    assert body["missing_actual_rates_doors"] == 0
    assert body["missing_addon_plans_facts"] == 0


def test_reports_projects_margin_returns_sorted_profitability(
    client_admin_real_uow,
    db_session,
    company_id,
    make_installer,
    make_door_type,
):
    installer = make_installer(full_name="Margin Installer", phone="+10000000992")
    door_type = make_door_type(name="Margin Door")
    suffix = uuid.uuid4().hex[:8]

    project_top = ProjectORM(
        company_id=company_id,
        name=f"Margin Top {suffix}",
        address=f"Margin Top Street {suffix}",
        status=ProjectStatus.OK,
    )
    project_low = ProjectORM(
        company_id=company_id,
        name=f"Margin Low {suffix}",
        address=f"Margin Low Street {suffix}",
        status=ProjectStatus.PROBLEM,
    )
    db_session.add_all([project_top, project_low])
    db_session.flush()

    rate = InstallerRateORM(
        company_id=company_id,
        installer_id=installer.id,
        door_type_id=door_type.id,
        effective_from=datetime.now(timezone.utc),
        price=Decimal("120.00"),
    )
    db_session.add(rate)

    db_session.add_all(
        [
            DoorORM(
                company_id=company_id,
                project_id=project_top.id,
                door_type_id=door_type.id,
                unit_label=f"MRG-{suffix}-1",
                our_price=Decimal("400.00"),
                status=DoorStatus.INSTALLED,
                installer_id=installer.id,
                installer_rate_snapshot=Decimal("100.00"),
                reason_id=None,
                comment=None,
                installed_at=datetime.now(timezone.utc),
                is_locked=False,
            ),
            DoorORM(
                company_id=company_id,
                project_id=project_low.id,
                door_type_id=door_type.id,
                unit_label=f"MRG-{suffix}-2",
                our_price=Decimal("150.00"),
                status=DoorStatus.INSTALLED,
                installer_id=installer.id,
                installer_rate_snapshot=Decimal("140.00"),
                reason_id=None,
                comment=None,
                installed_at=datetime.now(timezone.utc),
                is_locked=False,
            ),
        ]
    )
    db_session.commit()

    top_resp = client_admin_real_uow.get(
        "/api/v1/admin/reports/projects-margin?limit=5&sort_by=profit_total&sort_dir=desc"
    )
    assert top_resp.status_code == 200, top_resp.text
    top_body = top_resp.json()
    assert top_body["total"] >= 2
    assert top_body["items"][0]["project_name"].startswith("Margin Top ")
    assert Decimal(str(top_body["items"][0]["profit_total"])) == Decimal("300.00")
    assert top_body["items"][0]["project_status"] == "OK"

    risk_resp = client_admin_real_uow.get(
        "/api/v1/admin/reports/projects-margin?limit=5&sort_by=profit_total&sort_dir=asc"
    )
    assert risk_resp.status_code == 200, risk_resp.text
    risk_body = risk_resp.json()
    assert risk_body["items"][0]["project_name"].startswith("Margin Low ")
    assert Decimal(str(risk_body["items"][0]["profit_total"])) == Decimal("10.00")
    assert risk_body["items"][0]["project_status"] == "PROBLEM"


def test_reports_issues_addons_impact_returns_margin_leakage(
    client_admin_real_uow,
    db_session,
    company_id,
    make_door_type,
    make_installer,
    make_reason,
):
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)

    project = ProjectORM(
        company_id=company_id,
        name="Margin Leakage Project",
        address="Leakage Street",
        status=ProjectStatus.PROBLEM,
    )
    db_session.add(project)
    db_session.flush()

    installer = make_installer(full_name="Leakage Installer", phone="+10000000993")
    reason_blocked = make_reason(name="Site Blocked")
    reason_measure = make_reason(name="Wrong Measure")
    door_type = make_door_type(name="Leakage Door")

    db_session.add(
        InstallerRateORM(
            company_id=company_id,
            installer_id=installer.id,
            door_type_id=door_type.id,
            effective_from=now,
            price=Decimal("40.00"),
        )
    )
    db_session.flush()

    door_blocked = DoorORM(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label="ML-101",
        our_price=Decimal("100.00"),
        status=DoorStatus.NOT_INSTALLED,
        installer_id=installer.id,
        reason_id=reason_blocked.id,
        comment=None,
        installed_at=None,
        is_locked=False,
    )
    door_waiting = DoorORM(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label="ML-102",
        our_price=Decimal("120.00"),
        status=DoorStatus.NOT_INSTALLED,
        installer_id=installer.id,
        reason_id=reason_blocked.id,
        comment=None,
        installed_at=None,
        is_locked=False,
    )
    door_measure = DoorORM(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label="ML-103",
        our_price=Decimal("80.00"),
        status=DoorStatus.NOT_INSTALLED,
        installer_id=installer.id,
        reason_id=reason_measure.id,
        comment=None,
        installed_at=None,
        is_locked=False,
    )
    door_issue_only = DoorORM(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label="ML-104",
        our_price=Decimal("150.00"),
        status=DoorStatus.INSTALLED,
        installer_id=installer.id,
        reason_id=None,
        comment=None,
        installed_at=now,
        is_locked=True,
    )
    db_session.add_all([door_blocked, door_waiting, door_measure, door_issue_only])
    db_session.flush()

    db_session.add_all(
        [
            IssueORM(
                company_id=company_id,
                door_id=door_blocked.id,
                status=IssueStatus.OPEN,
                workflow_state=IssueWorkflowState.BLOCKED,
                priority=IssuePriority.P1,
                title="Blocked installation",
                details="Site access blocked",
                due_at=now - timedelta(hours=2),
            ),
            IssueORM(
                company_id=company_id,
                door_id=door_issue_only.id,
                status=IssueStatus.OPEN,
                workflow_state=IssueWorkflowState.TRIAGED,
                priority=IssuePriority.P2,
                title="Adjustment required",
                details="Follow-up visit",
                due_at=now + timedelta(days=1),
            ),
        ]
    )

    addon_planned = AddonTypeORM(
        company_id=company_id,
        name="Handle Upgrade",
        is_active=True,
    )
    addon_unplanned = AddonTypeORM(
        company_id=company_id,
        name="Rush Visit",
        is_active=True,
    )
    db_session.add_all([addon_planned, addon_unplanned])
    db_session.flush()

    db_session.add(
        ProjectAddonPlanORM(
            company_id=company_id,
            project_id=project.id,
            addon_type_id=addon_planned.id,
            qty_planned=Decimal("5.00"),
            client_price=Decimal("50.00"),
            installer_price=Decimal("20.00"),
        )
    )
    db_session.add_all(
        [
            ProjectAddonFactORM(
                company_id=company_id,
                project_id=project.id,
                addon_type_id=addon_planned.id,
                installer_id=installer.id,
                qty_done=Decimal("2.00"),
                done_at=now,
                comment=None,
                source=AddonFactSource.ONLINE,
                client_event_id=None,
            ),
            ProjectAddonFactORM(
                company_id=company_id,
                project_id=project.id,
                addon_type_id=addon_unplanned.id,
                installer_id=installer.id,
                qty_done=Decimal("1.00"),
                done_at=now,
                comment=None,
                source=AddonFactSource.ONLINE,
                client_event_id=None,
            ),
        ]
    )
    db_session.commit()

    resp = client_admin_real_uow.get("/api/v1/admin/reports/issues-addons-impact?limit=5")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    summary = body["summary"]
    assert summary["open_issues"] == 2
    assert summary["blocked_open_issues"] == 1
    assert summary["not_installed_doors"] == 3
    assert Decimal(str(summary["open_issue_revenue_at_risk"])) == Decimal("250.00")
    assert Decimal(str(summary["open_issue_payroll_at_risk"])) == Decimal("80.00")
    assert Decimal(str(summary["open_issue_profit_at_risk"])) == Decimal("170.00")
    assert Decimal(str(summary["blocked_issue_profit_at_risk"])) == Decimal("60.00")
    assert Decimal(str(summary["delayed_revenue_total"])) == Decimal("300.00")
    assert Decimal(str(summary["delayed_payroll_total"])) == Decimal("120.00")
    assert Decimal(str(summary["delayed_profit_total"])) == Decimal("180.00")
    assert Decimal(str(summary["addon_revenue_total"])) == Decimal("100.00")
    assert Decimal(str(summary["addon_payroll_total"])) == Decimal("40.00")
    assert Decimal(str(summary["addon_profit_total"])) == Decimal("60.00")
    assert summary["missing_addon_plans_facts"] == 1

    assert body["top_reasons"][0]["reason_name"] == "Site Blocked"
    assert body["top_reasons"][0]["doors"] == 2
    assert Decimal(str(body["top_reasons"][0]["profit_delayed_total"])) == Decimal("140.00")
    assert body["addon_impact"][0]["addon_name"] == "Handle Upgrade"
    assert Decimal(str(body["addon_impact"][0]["profit_total"])) == Decimal("60.00")


def test_reports_project_risk_drilldown_returns_loss_drivers(
    client_admin_real_uow,
    db_session,
    company_id,
    make_installer,
    make_door_type,
    make_reason,
):
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    installer = make_installer(full_name="Risk Drilldown Installer", phone="+10000001012")
    door_type = make_door_type(name="Risk Drilldown Door")
    reason_blocked = make_reason(name="Blocked Site")
    reason_measure = make_reason(name="Bad Measure")

    project = ProjectORM(
        company_id=company_id,
        name="Risk Drilldown Project",
        address="Risk Drilldown Street",
        status=ProjectStatus.PROBLEM,
    )
    db_session.add(project)
    db_session.flush()

    db_session.add(
        InstallerRateORM(
            company_id=company_id,
            installer_id=installer.id,
            door_type_id=door_type.id,
            effective_from=now,
            price=Decimal("50.00"),
        )
    )
    db_session.flush()

    door_installed = DoorORM(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label="RD-1",
        order_number="RISK-100",
        our_price=Decimal("200.00"),
        status=DoorStatus.INSTALLED,
        installer_id=installer.id,
        installer_rate_snapshot=Decimal("50.00"),
        reason_id=None,
        comment=None,
        installed_at=now,
        is_locked=False,
    )
    door_blocked = DoorORM(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label="RD-2",
        order_number="RISK-100",
        our_price=Decimal("180.00"),
        status=DoorStatus.NOT_INSTALLED,
        installer_id=installer.id,
        reason_id=reason_blocked.id,
        comment=None,
        installed_at=None,
        is_locked=False,
    )
    door_measure = DoorORM(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label="RD-3",
        order_number="RISK-200",
        our_price=Decimal("150.00"),
        status=DoorStatus.NOT_INSTALLED,
        installer_id=installer.id,
        reason_id=reason_measure.id,
        comment=None,
        installed_at=None,
        is_locked=False,
    )
    db_session.add_all([door_installed, door_blocked, door_measure])
    db_session.flush()

    db_session.add(
        IssueORM(
            company_id=company_id,
            door_id=door_blocked.id,
            status=IssueStatus.OPEN,
            workflow_state=IssueWorkflowState.BLOCKED,
            priority=IssuePriority.P1,
            title="Blocked issue",
            details=None,
            due_at=now,
        )
    )

    addon_type = AddonTypeORM(
        company_id=company_id,
        name="Risk Addon",
        unit="pcs",
        default_client_price=Decimal("30.00"),
        default_installer_price=Decimal("10.00"),
        is_active=True,
    )
    db_session.add(addon_type)
    db_session.flush()

    db_session.add(
        ProjectAddonPlanORM(
            company_id=company_id,
            project_id=project.id,
            addon_type_id=addon_type.id,
            qty_planned=Decimal("2.00"),
            client_price=Decimal("30.00"),
            installer_price=Decimal("10.00"),
        )
    )
    db_session.add(
        ProjectAddonFactORM(
            company_id=company_id,
            project_id=project.id,
            addon_type_id=addon_type.id,
            installer_id=installer.id,
            qty_done=Decimal("1.00"),
            done_at=now,
            comment=None,
            source=AddonFactSource.ONLINE,
            client_event_id=None,
        )
    )
    db_session.commit()

    resp = client_admin_real_uow.get(
        f"/api/v1/admin/reports/project-risk-drilldown/{project.id}?limit=5"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["project_id"] == str(project.id)
    assert body["project_name"] == "Risk Drilldown Project"
    assert body["summary"]["total_doors"] == 3
    assert body["summary"]["installed_doors"] == 1
    assert body["summary"]["not_installed_doors"] == 2
    assert body["summary"]["open_issues"] == 1
    assert body["summary"]["blocked_open_issues"] == 1
    assert Decimal(str(body["summary"]["planned_revenue_total"])) == Decimal("590.00")
    assert Decimal(str(body["summary"]["actual_revenue_total"])) == Decimal("230.00")
    assert Decimal(str(body["summary"]["revenue_gap_total"])) == Decimal("360.00")
    assert Decimal(str(body["summary"]["planned_profit_total"])) == Decimal("420.00")
    assert Decimal(str(body["summary"]["actual_profit_total"])) == Decimal("170.00")
    assert Decimal(str(body["summary"]["profit_gap_total"])) == Decimal("250.00")
    assert Decimal(str(body["summary"]["delayed_profit_total"])) == Decimal("230.00")
    assert Decimal(str(body["summary"]["blocked_issue_profit_at_risk"])) == Decimal("130.00")
    assert Decimal(str(body["summary"]["addon_profit_total"])) == Decimal("20.00")
    assert body["drivers"][0]["code"] == "profit_gap_total"
    assert body["top_reasons"][0]["reason_name"] == "Blocked Site"
    assert body["risky_orders"][0]["order_number"] == "RISK-100"
    assert Decimal(str(body["risky_orders"][0]["revenue_gap_total"])) == Decimal("180.00")


def test_reports_payroll_uses_installed_rate_snapshot(
    client_admin_real_uow,
    db_session,
    company_id,
    make_installer,
    make_door_type,
):
    installer = make_installer(full_name="Snapshot Installer")
    door_type = make_door_type(name="Snapshot Door")
    suffix = uuid.uuid4().hex[:8]
    project = ProjectORM(
        company_id=company_id,
        name=f"Snapshot Project {suffix}",
        address=f"Snapshot Street {suffix}",
        status=ProjectStatus.OK,
    )
    db_session.add(project)
    db_session.flush()

    door = DoorORM(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label=f"SNAP-{suffix}",
        our_price=Decimal("200.00"),
        status=DoorStatus.NOT_INSTALLED,
        installer_id=installer.id,
        reason_id=None,
        comment=None,
        installed_at=None,
        is_locked=False,
    )
    db_session.add(door)
    db_session.commit()

    create_rate_resp = client_admin_real_uow.post(
        "/api/v1/admin/installer-rates",
        json={
            "installer_id": str(installer.id),
            "door_type_id": str(door_type.id),
            "price": "100.00",
        },
    )
    assert create_rate_resp.status_code == 201, create_rate_resp.text
    rate_id = create_rate_resp.json()["id"]

    install_resp = client_admin_real_uow.post(f"/api/v1/admin/doors/{door.id}/install")
    assert install_resp.status_code == 200, install_resp.text

    db_session.expire_all()
    installed_door = (
        db_session.query(DoorORM)
        .filter(DoorORM.company_id == company_id, DoorORM.id == door.id)
        .one()
    )
    assert installed_door.status == DoorStatus.INSTALLED
    assert installed_door.installer_rate_snapshot == Decimal("100.00")

    update_rate_resp = client_admin_real_uow.patch(
        f"/api/v1/admin/installer-rates/{rate_id}",
        json={"price": "170.00"},
    )
    assert update_rate_resp.status_code == 200, update_rate_resp.text

    kpi_resp = client_admin_real_uow.get("/api/v1/admin/reports/kpi")
    assert kpi_resp.status_code == 200, kpi_resp.text
    kpi = kpi_resp.json()
    assert kpi["installed_doors"] == 1
    assert Decimal(str(kpi["revenue_total"])) == Decimal("200.00")
    assert Decimal(str(kpi["payroll_total"])) == Decimal("100.00")
    assert Decimal(str(kpi["profit_total"])) == Decimal("100.00")
    assert kpi["missing_rates_installed_doors"] == 0

    project_profit_resp = client_admin_real_uow.get(
        f"/api/v1/admin/reports/project-profit/{project.id}"
    )
    assert project_profit_resp.status_code == 200, project_profit_resp.text
    project_profit = project_profit_resp.json()
    assert project_profit["installed_doors"] == 1
    assert Decimal(str(project_profit["revenue_total"])) == Decimal("200.00")
    assert Decimal(str(project_profit["payroll_total"])) == Decimal("100.00")
    assert Decimal(str(project_profit["profit_total"])) == Decimal("100.00")
    assert project_profit["missing_rates_installed_doors"] == 0


def test_install_snapshot_uses_latest_effective_rate_at_install_time(
    client_admin_real_uow,
    db_session,
    company_id,
    make_installer,
    make_door_type,
):
    installer = make_installer(full_name="EffectiveFrom Installer")
    door_type = make_door_type(name="EffectiveFrom Door")
    suffix = uuid.uuid4().hex[:8]
    project = ProjectORM(
        company_id=company_id,
        name=f"EffectiveFrom Project {suffix}",
        address=f"EffectiveFrom Street {suffix}",
        status=ProjectStatus.OK,
    )
    db_session.add(project)
    db_session.flush()

    door = DoorORM(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label=f"EFF-{suffix}",
        our_price=Decimal("250.00"),
        status=DoorStatus.NOT_INSTALLED,
        installer_id=installer.id,
        reason_id=None,
        comment=None,
        installed_at=None,
        is_locked=False,
    )
    db_session.add(door)
    db_session.commit()

    now = datetime.now(timezone.utc).replace(microsecond=0)
    r1 = client_admin_real_uow.post(
        "/api/v1/admin/installer-rates",
        json={
            "installer_id": str(installer.id),
            "door_type_id": str(door_type.id),
            "price": "90.00",
            "effective_from": (now - timedelta(days=10)).isoformat(),
        },
    )
    assert r1.status_code == 201, r1.text
    r2 = client_admin_real_uow.post(
        "/api/v1/admin/installer-rates",
        json={
            "installer_id": str(installer.id),
            "door_type_id": str(door_type.id),
            "price": "110.00",
            "effective_from": (now - timedelta(days=1)).isoformat(),
        },
    )
    assert r2.status_code == 201, r2.text
    r3 = client_admin_real_uow.post(
        "/api/v1/admin/installer-rates",
        json={
            "installer_id": str(installer.id),
            "door_type_id": str(door_type.id),
            "price": "170.00",
            "effective_from": (now + timedelta(days=1)).isoformat(),
        },
    )
    assert r3.status_code == 201, r3.text

    install_resp = client_admin_real_uow.post(f"/api/v1/admin/doors/{door.id}/install")
    assert install_resp.status_code == 200, install_resp.text

    db_session.expire_all()
    installed = (
        db_session.query(DoorORM)
        .filter(DoorORM.company_id == company_id, DoorORM.id == door.id)
        .one()
    )
    assert installed.status == DoorStatus.INSTALLED
    assert installed.installer_rate_snapshot == Decimal("110.00")


def test_reports_forbidden_for_installer_role(client_installer):
    resp = client_installer.get("/api/v1/admin/reports/kpi")
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "FORBIDDEN"

    installers_kpi_resp = client_installer.get("/api/v1/admin/reports/installers-kpi")
    assert installers_kpi_resp.status_code == 403, installers_kpi_resp.text
    assert installers_kpi_resp.json()["error"]["code"] == "FORBIDDEN"

    installers_kpi_export_resp = client_installer.get(
        "/api/v1/admin/reports/installers-kpi/export"
    )
    assert installers_kpi_export_resp.status_code == 403, installers_kpi_export_resp.text
    assert installers_kpi_export_resp.json()["error"]["code"] == "FORBIDDEN"

    order_kpi_resp = client_installer.get("/api/v1/admin/reports/order-numbers-kpi")
    assert order_kpi_resp.status_code == 403, order_kpi_resp.text
    assert order_kpi_resp.json()["error"]["code"] == "FORBIDDEN"

    order_kpi_export_resp = client_installer.get(
        "/api/v1/admin/reports/order-numbers-kpi/export"
    )
    assert order_kpi_export_resp.status_code == 403, order_kpi_export_resp.text
    assert order_kpi_export_resp.json()["error"]["code"] == "FORBIDDEN"


def test_reports_limit_alerts_feed_and_mark_read(
    client_admin_real_uow,
    db_session,
    company_id,
    admin_user,
):
    now = datetime.now(timezone.utc)
    old_alert = AuditLogORM(
        company_id=company_id,
        actor_user_id=admin_user.id,
        entity_type="company_plan",
        entity_id=company_id,
        action="PLAN_LIMIT_ALERT_WARN_USERS",
        before=None,
        after={
            "metric": "users",
            "level": "WARN",
            "current": 8,
            "max": 10,
            "utilization_pct": 80.0,
            "plan_code": "trial",
        },
    )
    new_alert = AuditLogORM(
        company_id=company_id,
        actor_user_id=admin_user.id,
        entity_type="company_plan",
        entity_id=company_id,
        action="PLAN_LIMIT_ALERT_DANGER_USERS",
        before=None,
        after={
            "metric": "users",
            "level": "DANGER",
            "current": 10,
            "max": 10,
            "utilization_pct": 100.0,
            "plan_code": "trial",
        },
    )
    db_session.add_all([old_alert, new_alert])
    db_session.flush()
    old_alert.created_at = now - timedelta(minutes=10)
    old_alert.updated_at = now - timedelta(minutes=10)
    new_alert.created_at = now
    new_alert.updated_at = now
    db_session.add_all([old_alert, new_alert])
    db_session.commit()

    feed_resp = client_admin_real_uow.get("/api/v1/admin/reports/limit-alerts")
    assert feed_resp.status_code == 200, feed_resp.text
    feed = feed_resp.json()
    assert feed["unread_count"] >= 2
    assert len(feed["items"]) >= 2
    assert feed["items"][0]["action"].startswith("PLAN_LIMIT_ALERT_")
    assert feed["items"][0]["is_unread"] is True
    assert feed["last_read_at"] is None

    mark_resp = client_admin_real_uow.post(
        "/api/v1/admin/reports/limit-alerts/read",
        json={"read_up_to": now.isoformat()},
    )
    assert mark_resp.status_code == 200, mark_resp.text
    marked = mark_resp.json()
    assert marked["unread_count"] == 0
    assert marked["last_read_at"] is not None

    feed_after = client_admin_real_uow.get("/api/v1/admin/reports/limit-alerts")
    assert feed_after.status_code == 200, feed_after.text
    after_body = feed_after.json()
    assert after_body["unread_count"] == 0
    assert all(item["is_unread"] is False for item in after_body["items"][:2])


def test_reports_operations_center_returns_aggregated_snapshot(
    client_admin_real_uow,
    db_session,
    company_id,
    admin_user,
):
    now = datetime.now(timezone.utc)
    project = ProjectORM(
        company_id=company_id,
        name="Ops Center Project",
        address="Ops Street 1",
        status=ProjectStatus.OK,
    )
    db_session.add(project)
    db_session.flush()

    runs = [
        ProjectImportRunORM(
            company_id=company_id,
            project_id=project.id,
            fingerprint="ops-failed",
            import_mode="import",
            source_filename="failed.csv",
            mapping_profile="auto_v1",
            result_payload={
                "imported": 0,
                "errors": [{"message": "missing required column"}],
            },
        ),
        ProjectImportRunORM(
            company_id=company_id,
            project_id=project.id,
            fingerprint="ops-success",
            import_mode="import",
            source_filename="success.csv",
            mapping_profile="auto_v1",
            result_payload={"imported": 5, "errors": []},
        ),
        ProjectImportRunORM(
            company_id=company_id,
            project_id=project.id,
            fingerprint="ops-partial",
            import_mode="import_retry",
            source_filename="retry.csv",
            mapping_profile="auto_v1",
            result_payload={
                "imported": 2,
                "errors": [{"message": "unit already exists"}],
            },
        ),
        ProjectImportRunORM(
            company_id=company_id,
            project_id=project.id,
            fingerprint="ops-analyze",
            import_mode="analyze",
            source_filename="analyze.csv",
            mapping_profile="auto_v1",
            result_payload={"imported": 0, "errors": []},
        ),
    ]
    db_session.add_all(runs)
    db_session.flush()
    runs[0].created_at = now - timedelta(hours=2)
    runs[1].created_at = now - timedelta(hours=1, minutes=30)
    runs[2].created_at = now - timedelta(hours=1)
    runs[3].created_at = now - timedelta(minutes=45)
    for run in runs:
        run.updated_at = run.created_at
    db_session.add_all(runs)

    outbox_items = [
        OutboxMessageORM(
            company_id=company_id,
            channel=OutboxChannel.EMAIL,
            status=OutboxStatus.FAILED,
            correlation_id=None,
            payload={"kind": "test"},
            attempts=5,
            max_attempts=5,
            last_error="smtp down",
            scheduled_at=now - timedelta(minutes=60),
            sent_at=None,
            provider_message_id=None,
            provider_status=None,
            provider_error="smtp down",
            delivery_status=DeliveryStatus.FAILED,
            delivered_at=None,
        ),
        OutboxMessageORM(
            company_id=company_id,
            channel=OutboxChannel.WHATSAPP,
            status=OutboxStatus.PENDING,
            correlation_id=None,
            payload={"kind": "test"},
            attempts=1,
            max_attempts=5,
            last_error=None,
            scheduled_at=now - timedelta(minutes=40),
            sent_at=None,
            provider_message_id=None,
            provider_status=None,
            provider_error=None,
            delivery_status=DeliveryStatus.PENDING,
            delivered_at=None,
        ),
    ]
    db_session.add_all(outbox_items)

    warn_alert = AuditLogORM(
        company_id=company_id,
        actor_user_id=admin_user.id,
        entity_type="company_plan",
        entity_id=company_id,
        action="PLAN_LIMIT_ALERT_WARN_USERS",
        before=None,
        after={"metric": "users", "level": "WARN"},
    )
    danger_alert = AuditLogORM(
        company_id=company_id,
        actor_user_id=admin_user.id,
        entity_type="company_plan",
        entity_id=company_id,
        action="PLAN_LIMIT_ALERT_DANGER_USERS",
        before=None,
        after={"metric": "users", "level": "DANGER"},
    )
    db_session.add_all([warn_alert, danger_alert])
    db_session.flush()
    warn_alert.created_at = now - timedelta(minutes=20)
    warn_alert.updated_at = warn_alert.created_at
    danger_alert.created_at = now - timedelta(minutes=2)
    danger_alert.updated_at = danger_alert.created_at
    db_session.add_all([warn_alert, danger_alert])

    db_session.add(
        AuditAlertReadCursorORM(
            company_id=company_id,
            user_id=admin_user.id,
            last_read_at=now - timedelta(minutes=5),
        )
    )
    db_session.commit()

    resp = client_admin_real_uow.get("/api/v1/admin/reports/operations-center")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["imports"]["window_hours"] == 24
    assert body["imports"]["total_runs"] == 4
    assert body["imports"]["analyze_runs"] == 1
    assert body["imports"]["import_runs"] == 2
    assert body["imports"]["retry_runs"] == 1
    assert body["imports"]["success_runs"] == 1
    assert body["imports"]["partial_runs"] == 1
    assert body["imports"]["failed_runs"] == 1
    assert body["outbox"]["total"] >= 2
    assert body["outbox"]["failed_total"] >= 1
    assert body["outbox"]["pending_overdue_15m"] >= 1
    assert body["outbox"]["by_channel"]["EMAIL"] >= 1
    assert body["outbox"]["by_channel"]["WHATSAPP"] >= 1
    assert body["alerts"]["total_last_24h"] >= 2
    assert body["alerts"]["warn_last_24h"] >= 1
    assert body["alerts"]["danger_last_24h"] >= 1
    assert body["alerts"]["unread_count"] >= 1
    assert len(body["top_failing_projects"]) >= 1
    top_project = body["top_failing_projects"][0]
    assert top_project["project_id"] == str(project.id)
    assert top_project["failure_runs"] >= 2


def test_reports_operations_sla_returns_metrics_and_playbooks(
    client_admin_real_uow,
    db_session,
    company_id,
    admin_user,
):
    now = datetime.now(timezone.utc)
    project = ProjectORM(
        company_id=company_id,
        name="Ops SLA Project",
        address="Ops SLA Street",
        status=ProjectStatus.OK,
    )
    db_session.add(project)
    db_session.flush()

    db_session.add(
        ProjectImportRunORM(
            company_id=company_id,
            project_id=project.id,
            fingerprint="ops-sla-failed",
            import_mode="import",
            source_filename="ops_sla_failed.csv",
            mapping_profile="auto_v1",
            result_payload={"imported": 0, "errors": [{"message": "invalid row"}]},
        )
    )
    db_session.add(
        OutboxMessageORM(
            company_id=company_id,
            channel=OutboxChannel.EMAIL,
            status=OutboxStatus.FAILED,
            correlation_id=None,
            payload={"kind": "ops_sla"},
            attempts=3,
            max_attempts=5,
            last_error="provider timeout",
            scheduled_at=now - timedelta(minutes=30),
            sent_at=None,
            provider_message_id=None,
            provider_status=None,
            provider_error="provider timeout",
            delivery_status=DeliveryStatus.FAILED,
            delivered_at=None,
        )
    )
    db_session.add(
        AuditLogORM(
            company_id=company_id,
            actor_user_id=admin_user.id,
            entity_type="company_plan",
            entity_id=company_id,
            action="PLAN_LIMIT_ALERT_DANGER_USERS",
            before=None,
            after={"metric": "users", "level": "DANGER"},
        )
    )
    db_session.commit()

    resp = client_admin_real_uow.get("/api/v1/admin/reports/operations-sla")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["overall_status"] in {"OK", "WARN", "DANGER"}
    assert isinstance(body["metrics"], list)
    assert len(body["metrics"]) >= 5
    metric_codes = {item["code"] for item in body["metrics"]}
    assert "imports_failure_rate_24h" in metric_codes
    assert "outbox_failed_rate" in metric_codes
    assert "outbox_pending_overdue_15m" in metric_codes
    assert "limit_alerts_danger_24h" in metric_codes
    assert "sync_danger_installers" in metric_codes
    assert all(item["status"] in {"OK", "WARN", "DANGER"} for item in body["metrics"])

    assert isinstance(body["playbooks"], list)
    assert len(body["playbooks"]) >= 1
    assert all(
        item["severity"] in {"OK", "WARN", "DANGER"} for item in body["playbooks"]
    )


def test_reports_operations_sla_history_returns_daily_points(
    client_admin_real_uow,
    db_session,
    company_id,
    admin_user,
):
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    prev_day = now - timedelta(days=1)

    project = ProjectORM(
        company_id=company_id,
        name="Ops SLA History Project",
        address="Ops SLA History Street",
        status=ProjectStatus.OK,
    )
    db_session.add(project)
    db_session.flush()

    db_session.add_all(
        [
            ProjectImportRunORM(
                company_id=company_id,
                project_id=project.id,
                fingerprint=f"ops-sla-hist-prev-{uuid.uuid4().hex[:8]}",
                import_mode="import",
                source_filename="history_prev_failed.csv",
                mapping_profile="auto_v1",
                result_payload={"imported": 0, "errors": [{"message": "bad row"}]},
                created_at=prev_day,
            ),
            ProjectImportRunORM(
                company_id=company_id,
                project_id=project.id,
                fingerprint=f"ops-sla-hist-now-{uuid.uuid4().hex[:8]}",
                import_mode="import",
                source_filename="history_now_ok.csv",
                mapping_profile="auto_v1",
                result_payload={"imported": 5, "errors": []},
                created_at=now,
            ),
            OutboxMessageORM(
                company_id=company_id,
                channel=OutboxChannel.EMAIL,
                status=OutboxStatus.FAILED,
                correlation_id=None,
                payload={"kind": "sla_history_prev"},
                attempts=2,
                max_attempts=5,
                last_error="provider timeout",
                scheduled_at=prev_day,
                sent_at=None,
                provider_message_id=None,
                provider_status=None,
                provider_error="provider timeout",
                delivery_status=DeliveryStatus.FAILED,
                delivered_at=None,
                created_at=prev_day,
            ),
            OutboxMessageORM(
                company_id=company_id,
                channel=OutboxChannel.EMAIL,
                status=OutboxStatus.SENT,
                correlation_id=None,
                payload={"kind": "sla_history_now"},
                attempts=1,
                max_attempts=5,
                last_error=None,
                scheduled_at=now,
                sent_at=now,
                provider_message_id="ok-now",
                provider_status="accepted",
                provider_error=None,
                delivery_status=DeliveryStatus.DELIVERED,
                delivered_at=now,
                created_at=now,
            ),
            AuditLogORM(
                company_id=company_id,
                actor_user_id=admin_user.id,
                entity_type="company_plan",
                entity_id=company_id,
                action="PLAN_LIMIT_ALERT_DANGER_USERS",
                before=None,
                after={"metric": "users", "level": "DANGER"},
                created_at=prev_day,
            ),
        ]
    )
    db_session.commit()

    resp = client_admin_real_uow.get("/api/v1/admin/reports/operations-sla/history?days=7")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["days"] == 7
    assert len(body["points"]) == 7
    assert body["summary"]["current_status"] in {"OK", "WARN", "DANGER"}
    assert body["summary"]["ok_days"] + body["summary"]["warn_days"] + body["summary"]["danger_days"] == 7

    points_by_day = {item["day"]: item for item in body["points"]}
    prev_key = prev_day.date().isoformat()
    now_key = now.date().isoformat()
    assert prev_key in points_by_day
    assert now_key in points_by_day

    assert points_by_day[prev_key]["import_runs"] >= 1
    assert points_by_day[prev_key]["risky_import_runs"] >= 1
    assert points_by_day[prev_key]["outbox_failed"] >= 1
    assert points_by_day[prev_key]["danger_alerts_count"] >= 1


def test_reports_issues_analytics_returns_incident_metrics(
    client_admin_real_uow,
    db_session,
    company_id,
    make_door_type,
):
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)

    project = ProjectORM(
        company_id=company_id,
        name="Issues Analytics Project",
        address="Issues Analytics Street",
        status=ProjectStatus.OK,
    )
    db_session.add(project)
    db_session.flush()

    door_type = make_door_type(name="Issues Analytics Door")

    door_open = DoorORM(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label="IA-OPEN",
        our_price=Decimal("100.00"),
        status=DoorStatus.NOT_INSTALLED,
        installer_id=None,
        reason_id=None,
        comment=None,
        installed_at=None,
        is_locked=False,
    )
    door_closed = DoorORM(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label="IA-CLOSED",
        our_price=Decimal("100.00"),
        status=DoorStatus.NOT_INSTALLED,
        installer_id=None,
        reason_id=None,
        comment=None,
        installed_at=None,
        is_locked=False,
    )
    door_triaged = DoorORM(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label="IA-TRIAGED",
        our_price=Decimal("100.00"),
        status=DoorStatus.NOT_INSTALLED,
        installer_id=None,
        reason_id=None,
        comment=None,
        installed_at=None,
        is_locked=False,
    )
    db_session.add_all([door_open, door_closed, door_triaged])
    db_session.flush()

    issue_open = IssueORM(
        company_id=company_id,
        door_id=door_open.id,
        status=IssueStatus.OPEN,
        workflow_state=IssueWorkflowState.BLOCKED,
        priority=IssuePriority.P1,
        title="Blocked at site",
        details="Waiting for permit",
        due_at=now - timedelta(hours=6),
    )
    issue_closed = IssueORM(
        company_id=company_id,
        door_id=door_closed.id,
        status=IssueStatus.CLOSED,
        workflow_state=IssueWorkflowState.CLOSED,
        priority=IssuePriority.P2,
        title="Closed incident",
        details="Resolved",
        due_at=None,
    )
    issue_triaged = IssueORM(
        company_id=company_id,
        door_id=door_triaged.id,
        status=IssueStatus.OPEN,
        workflow_state=IssueWorkflowState.TRIAGED,
        priority=IssuePriority.P3,
        title="New triage",
        details="Needs assignment",
        due_at=now + timedelta(days=1),
    )
    db_session.add_all([issue_open, issue_closed, issue_triaged])
    db_session.flush()

    issue_open.created_at = now - timedelta(days=2)
    issue_open.updated_at = now - timedelta(days=1)
    issue_closed.created_at = now - timedelta(days=4)
    issue_closed.updated_at = now - timedelta(days=1, hours=6)
    issue_triaged.created_at = now - timedelta(hours=8)
    issue_triaged.updated_at = now - timedelta(hours=1)
    db_session.add_all([issue_open, issue_closed, issue_triaged])
    db_session.commit()

    resp = client_admin_real_uow.get("/api/v1/admin/reports/issues-analytics?days=30")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["days"] == 30
    assert body["summary"]["total_issues"] >= 3
    assert body["summary"]["open_issues"] >= 2
    assert body["summary"]["closed_issues"] >= 1
    assert body["summary"]["overdue_open_issues"] >= 1
    assert body["summary"]["blocked_open_issues"] >= 1
    assert body["summary"]["p1_open_issues"] >= 1
    assert body["summary"]["overdue_open_rate_pct"] > 0
    assert body["summary"]["mttr_sample_size"] >= 1
    assert body["summary"]["mttr_hours"] >= 0
    assert body["summary"]["mttr_p50_hours"] >= 0
    assert body["summary"]["backlog_by_workflow"]["BLOCKED"] >= 1
    assert body["summary"]["backlog_by_priority"]["P1"] >= 1

    assert len(body["trend"]) == 30
    assert all("day" in item for item in body["trend"])
    assert all("opened" in item for item in body["trend"])
    assert all("closed" in item for item in body["trend"])
    assert all("backlog_open_end" in item for item in body["trend"])


def test_reports_audit_issues_endpoint_and_export(
    client_admin_real_uow,
    db_session,
    company_id,
    make_door_type,
):
    issue1 = _seed_issue_report_row(
        db_session,
        company_id=company_id,
        make_door_type=make_door_type,
        unit_label="AU-101",
    )
    issue2 = _seed_issue_report_row(
        db_session,
        company_id=company_id,
        make_door_type=make_door_type,
        unit_label="AU-102",
    )

    update_one = client_admin_real_uow.patch(
        f"/api/v1/admin/issues/{issue1.id}/workflow",
        json={"workflow_state": "TRIAGED", "details": "triaged by report test"},
    )
    assert update_one.status_code == 200, update_one.text

    update_bulk = client_admin_real_uow.patch(
        "/api/v1/admin/issues/workflow/bulk",
        json={
            "issue_ids": [str(issue1.id), str(issue2.id)],
            "workflow_state": "IN_PROGRESS",
            "details": "bulk progress",
        },
    )
    assert update_bulk.status_code == 200, update_bulk.text
    assert update_bulk.json()["updated"] == 2

    report_resp = client_admin_real_uow.get("/api/v1/admin/reports/audit-issues")
    assert report_resp.status_code == 200, report_resp.text
    payload = report_resp.json()
    assert payload["summary"]["total"] >= 3
    assert payload["summary"]["by_entity"].get("issue", 0) >= 3
    actions = {x["action"] for x in payload["items"]}
    assert "ISSUE_WORKFLOW_UPDATE" in actions
    assert "ISSUE_WORKFLOW_BULK_UPDATE" in actions
    assert all(x["entity_type"] == "issue" for x in payload["items"])

    filtered = client_admin_real_uow.get(
        "/api/v1/admin/reports/audit-issues?action=ISSUE_WORKFLOW_BULK_UPDATE"
    )
    assert filtered.status_code == 200, filtered.text
    filtered_payload = filtered.json()
    assert filtered_payload["items"]
    assert all(
        x["action"] == "ISSUE_WORKFLOW_BULK_UPDATE"
        for x in filtered_payload["items"]
    )

    filtered_by_issue = client_admin_real_uow.get(
        f"/api/v1/admin/reports/audit-issues?issue_id={issue2.id}"
    )
    assert filtered_by_issue.status_code == 200, filtered_by_issue.text
    by_issue_payload = filtered_by_issue.json()
    assert by_issue_payload["summary"]["total"] >= 1
    assert by_issue_payload["items"]
    assert all(x["entity_id"] == str(issue2.id) for x in by_issue_payload["items"])

    bad_filter = client_admin_real_uow.get(
        "/api/v1/admin/reports/audit-issues?action=DOOR_TYPE_CREATE"
    )
    assert bad_filter.status_code == 422, bad_filter.text
    assert bad_filter.json()["error"]["code"] == "VALIDATION_ERROR"

    bad_issue_filter = client_admin_real_uow.get(
        "/api/v1/admin/reports/audit-issues?issue_id=not-a-uuid"
    )
    assert bad_issue_filter.status_code == 422, bad_issue_filter.text
    assert bad_issue_filter.json()["error"]["code"] == "VALIDATION_ERROR"

    export_resp = client_admin_real_uow.get(
        f"/api/v1/admin/reports/audit-issues/export?action=ISSUE_WORKFLOW_BULK_UPDATE&issue_id={issue1.id}"
    )
    assert export_resp.status_code == 200, export_resp.text
    assert export_resp.headers["content-type"].startswith("text/csv")
    assert "attachment;" in export_resp.headers["content-disposition"]
    csv_body = export_resp.text
    assert (
        "id,created_at,actor_user_id,entity_type,entity_id,action,reason,before,after"
        in csv_body
    )
    assert "ISSUE_WORKFLOW_BULK_UPDATE" in csv_body
