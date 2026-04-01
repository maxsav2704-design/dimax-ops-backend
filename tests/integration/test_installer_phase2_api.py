from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.api.v1.acl import get_current_installer_id
from app.api.v1.deps import CurrentUser, require_installer
from app.main import create_app
from app.modules.calendar.domain.enums import CalendarEventType
from app.modules.calendar.infrastructure.models import CalendarEventAssigneeORM, CalendarEventORM
from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.earnings.infrastructure.models import CompletedWorkORM
from app.modules.issues.infrastructure.models import IssueORM
from app.modules.installers.infrastructure.models import InstallerORM
from app.modules.projects.domain.enums import ProjectStatus
from app.modules.projects.infrastructure.models import ProjectORM
from app.modules.sync.infrastructure.models import SyncQueueItemORM


@pytest.fixture()
def installer_client_phase2(installer_user: CurrentUser, db_session):
    installer = InstallerORM(
        company_id=installer_user.company_id,
        full_name="Installer Phase2",
        phone=f"+1555{uuid.uuid4().hex[:8]}",
        email=None,
        address=None,
        passport_id=None,
        notes=None,
        status="ACTIVE",
        is_active=True,
        user_id=installer_user.id,
    )
    db_session.add(installer)
    db_session.commit()
    db_session.refresh(installer)

    app = create_app()

    def _require_installer() -> CurrentUser:
        return installer_user

    def _get_current_installer_id() -> uuid.UUID:
        return installer.id

    app.dependency_overrides[require_installer] = _require_installer
    app.dependency_overrides[get_current_installer_id] = _get_current_installer_id

    with TestClient(app) as test_client:
        yield test_client, installer.id, installer_user

    app.dependency_overrides.clear()


def _make_project(*, company_id: uuid.UUID, name: str, address: str, status: ProjectStatus = ProjectStatus.OK) -> ProjectORM:
    return ProjectORM(
        company_id=company_id,
        name=name,
        address=address,
        code=f"PRJ-{uuid.uuid4().hex[:6].upper()}",
        status=status,
        lifecycle_status="ACTIVE",
        health_status="NORMAL",
    )


def _make_door(
    *,
    company_id: uuid.UUID,
    project_id: uuid.UUID,
    door_type_id: uuid.UUID,
    unit_label: str,
    installer_id: uuid.UUID | None,
    status: DoorStatus = DoorStatus.NOT_INSTALLED,
    is_critical: bool = False,
) -> DoorORM:
    return DoorORM(
        company_id=company_id,
        project_id=project_id,
        door_type_id=door_type_id,
        unit_label=unit_label,
        door_code=f"{unit_label}-{uuid.uuid4().hex[:4]}",
        our_price=Decimal("100.00"),
        status=status,
        installer_id=installer_id,
        reason_id=None,
        comment=None,
        installed_at=None,
        is_locked=False,
        is_critical=is_critical,
        version=0,
        surcharge_pct=Decimal("100.00"),
    )


def test_door_status_installer_can_set_in_progress(
    installer_client_phase2,
    db_session,
    company_id,
    make_door_type,
):
    client, installer_id, _user = installer_client_phase2
    project = _make_project(company_id=company_id, name="State Machine", address="A")
    door_type = make_door_type(name="State Door")
    db_session.add(project)
    db_session.flush()
    door = _make_door(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label="A-01",
        installer_id=installer_id,
    )
    db_session.add(door)
    db_session.commit()

    resp = client.patch(
        f"/api/v1/installer/doors/{door.id}/status",
        json={"status": "IN_PROGRESS"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "IN_PROGRESS"
    assert body["version"] == 1

    db_session.refresh(door)
    assert door.status == DoorStatus.IN_PROGRESS


def test_door_status_installer_can_set_installed(
    installer_client_phase2,
    db_session,
    company_id,
    make_door_type,
):
    client, installer_id, _user = installer_client_phase2
    project = _make_project(company_id=company_id, name="Installed Flow", address="B")
    door_type = make_door_type(name="Installed Door")
    db_session.add(project)
    db_session.flush()
    door = _make_door(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label="B-01",
        installer_id=installer_id,
        status=DoorStatus.IN_PROGRESS,
    )
    db_session.add(door)
    db_session.commit()

    resp = client.patch(
        f"/api/v1/installer/doors/{door.id}/status",
        json={"status": "INSTALLED"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "INSTALLED"

    db_session.refresh(door)
    assert door.status == DoorStatus.INSTALLED
    assert door.is_locked is True


def test_door_status_installer_cannot_set_cancelled(
    installer_client_phase2,
    db_session,
    company_id,
    make_door_type,
):
    client, installer_id, _user = installer_client_phase2
    project = _make_project(company_id=company_id, name="Invalid Flow", address="C")
    door_type = make_door_type(name="Invalid Door")
    db_session.add(project)
    db_session.flush()
    door = _make_door(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label="C-01",
        installer_id=installer_id,
    )
    db_session.add(door)
    db_session.commit()

    resp = client.patch(
        f"/api/v1/installer/doors/{door.id}/status",
        json={"status": "INSTALLED"},
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error"] == {
        "code": "INVALID_TRANSITION",
        "message": "Door cannot move from NOT_INSTALLED to INSTALLED",
        "field": "status",
        "meta": {
            "door_id": str(door.id),
            "from_status": "NOT_INSTALLED",
            "to_status": "INSTALLED",
        },
    }


def test_door_status_installer_cannot_change_other_door(
    installer_client_phase2,
    db_session,
    company_id,
    make_door_type,
    make_installer,
):
    client, installer_id, _user = installer_client_phase2
    other_installer = make_installer(full_name="Other", phone="+972500000777")
    project = _make_project(company_id=company_id, name="Forbidden", address="D")
    door_type = make_door_type(name="Forbidden Door")
    db_session.add(project)
    db_session.flush()
    door = _make_door(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label="D-01",
        installer_id=other_installer.id,
    )
    db_session.add(door)
    db_session.commit()

    resp = client.patch(
        f"/api/v1/installer/doors/{door.id}/status",
        json={"status": "IN_PROGRESS"},
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "DOOR_NOT_ASSIGNED"


def test_door_status_installed_creates_completed_work_row(
    installer_client_phase2,
    db_session,
    company_id,
    make_door_type,
):
    client, installer_id, _user = installer_client_phase2
    project = _make_project(company_id=company_id, name="Ledger Flow", address="E")
    door_type = make_door_type(name="Ledger Door")
    db_session.add(project)
    db_session.flush()
    door = _make_door(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label="E-01",
        installer_id=installer_id,
        status=DoorStatus.IN_PROGRESS,
    )
    door.installer_rate_snapshot = Decimal("77.00")
    db_session.add(door)
    db_session.commit()

    resp = client.patch(
        f"/api/v1/installer/doors/{door.id}/status",
        json={"status": "INSTALLED"},
    )
    assert resp.status_code == 200, resp.text

    row = (
        db_session.query(CompletedWorkORM)
        .filter(CompletedWorkORM.company_id == company_id, CompletedWorkORM.door_id == door.id)
        .one()
    )
    assert row.entry_type == "ORIGINAL"
    assert Decimal(str(row.amount_snapshot)) == Decimal("77.00")


def test_installer_can_create_issue_and_open_door(
    installer_client_phase2,
    db_session,
    company_id,
    make_door_type,
):
    client, installer_id, user = installer_client_phase2
    project = _make_project(company_id=company_id, name="Issue Flow", address="F")
    door_type = make_door_type(name="Issue Door")
    db_session.add(project)
    db_session.flush()
    door = _make_door(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label="F-01",
        installer_id=installer_id,
    )
    db_session.add(door)
    db_session.commit()

    resp = client.post(
        "/api/v1/installer/issues",
        json={"door_id": str(door.id), "title": "Broken frame", "details": "Need check"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["door_id"] == str(door.id)
    assert body["status"] == "OPEN"
    assert body["workflow_state"] == "NEW"

    db_session.refresh(door)
    assert door.status == DoorStatus.ISSUE_OPEN
    assert door.version == 1

    issue = db_session.query(IssueORM).filter(IssueORM.door_id == door.id).one()
    assert issue.created_by_user_id == user.id


def test_installer_can_list_own_created_issues(
    installer_client_phase2,
    db_session,
    company_id,
    make_door_type,
):
    client, installer_id, user = installer_client_phase2
    project = _make_project(company_id=company_id, name="Issue List", address="G")
    door_type = make_door_type(name="Issue List Door")
    db_session.add(project)
    db_session.flush()
    door = _make_door(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label="G-01",
        installer_id=installer_id,
    )
    db_session.add(door)
    db_session.flush()
    issue = IssueORM(
        company_id=company_id,
        door_id=door.id,
        status="OPEN",
        workflow_state="NEW",
        priority="P3",
        title="Visible issue",
        details="Mine",
        created_by_user_id=user.id,
        owner_user_id=user.id,
    )
    db_session.add(issue)
    db_session.commit()

    resp = client.get("/api/v1/installer/issues")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["id"] == str(issue.id)
    assert body["items"][0]["project_id"] == str(project.id)
    assert body["pagination"] == {
        "page": 1,
        "per_page": 25,
        "total": 1,
        "total_pages": 1,
    }


def test_installer_sync_queue_list_has_pagination_object(
    installer_client_phase2,
    db_session,
    company_id,
):
    client, _installer_id, user = installer_client_phase2
    db_session.add(
        SyncQueueItemORM(
            company_id=company_id,
            user_id=user.id,
            device_id="audit-device",
            entity_type="door",
            entity_id=uuid.uuid4(),
            operation_type="DOOR_SET_STATUS",
            payload={"status": "IN_PROGRESS"},
            base_version=2,
            status="PENDING",
            conflict_code=None,
            created_at=datetime.now(timezone.utc),
            synced_at=None,
        )
    )
    db_session.commit()

    resp = client.get("/api/v1/installer/sync-queue")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["items"]) == 1
    assert body["pagination"] == {
        "page": 1,
        "per_page": 25,
        "total": 1,
        "total_pages": 1,
    }


def test_installer_earnings_summary_excludes_financial_leakage(
    installer_client_phase2,
    db_session,
    company_id,
    make_door_type,
):
    client, installer_id, _user = installer_client_phase2
    project = _make_project(company_id=company_id, name="Earnings", address="H")
    door_type = make_door_type(name="Earnings Door")
    db_session.add(project)
    db_session.flush()
    door = _make_door(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label="H-01",
        installer_id=installer_id,
    )
    db_session.add(door)
    db_session.flush()
    db_session.add(
        CompletedWorkORM(
            company_id=company_id,
            project_id=project.id,
            door_id=door.id,
            installer_id=installer_id,
            completed_at=datetime.now(timezone.utc),
            quantity=Decimal("1.00"),
            rate_snapshot=Decimal("50.00"),
            amount_snapshot=Decimal("50.00"),
            entry_type="ORIGINAL",
        )
    )
    db_session.commit()

    resp = client.get("/api/v1/installer/earnings/summary?period=day")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == "50.00"
    assert "client_rate" not in body
    assert "margin" not in body
    assert "surcharge_pct" not in body


def test_installer_earnings_summary_excludes_superseded_originals(
    installer_client_phase2,
    db_session,
    company_id,
    make_door_type,
):
    client, installer_id, _user = installer_client_phase2
    project = _make_project(company_id=company_id, name="Corrections", address="J")
    door_type = make_door_type(name="Correction Door")
    db_session.add(project)
    db_session.flush()
    door = _make_door(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label="J-01",
        installer_id=installer_id,
    )
    db_session.add(door)
    db_session.flush()
    original = CompletedWorkORM(
        company_id=company_id,
        project_id=project.id,
        door_id=door.id,
        installer_id=installer_id,
        completed_at=datetime.now(timezone.utc),
        quantity=Decimal("1.00"),
        rate_snapshot=Decimal("40.00"),
        amount_snapshot=Decimal("40.00"),
        entry_type="ORIGINAL",
    )
    db_session.add(original)
    db_session.flush()
    db_session.add(
        CompletedWorkORM(
            company_id=company_id,
            project_id=project.id,
            door_id=door.id,
            installer_id=installer_id,
            completed_at=datetime.now(timezone.utc),
            quantity=Decimal("1.00"),
            rate_snapshot=Decimal("-40.00"),
            amount_snapshot=Decimal("-40.00"),
            entry_type="REVERSAL",
            correction_ref_id=original.id,
        )
    )
    db_session.add(
        CompletedWorkORM(
            company_id=company_id,
            project_id=project.id,
            door_id=door.id,
            installer_id=installer_id,
            completed_at=datetime.now(timezone.utc),
            quantity=Decimal("1.00"),
            rate_snapshot=Decimal("55.00"),
            amount_snapshot=Decimal("55.00"),
            entry_type="CORRECTION",
            correction_ref_id=original.id,
        )
    )
    db_session.commit()

    resp = client.get("/api/v1/installer/earnings/summary?period=day")
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == "55.00"


def test_installer_monthly_earnings_summary_returns_weekly_breakdown(
    installer_client_phase2,
    db_session,
    company_id,
    make_door_type,
):
    client, installer_id, _user = installer_client_phase2
    project = _make_project(company_id=company_id, name="Monthly", address="K")
    door_type = make_door_type(name="Monthly Door")
    db_session.add(project)
    db_session.flush()
    door = _make_door(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label="K-01",
        installer_id=installer_id,
    )
    db_session.add(door)
    db_session.flush()
    db_session.add(
        CompletedWorkORM(
            company_id=company_id,
            project_id=project.id,
            door_id=door.id,
            installer_id=installer_id,
            completed_at=datetime.now(timezone.utc),
            quantity=Decimal("1.00"),
            rate_snapshot=Decimal("60.00"),
            amount_snapshot=Decimal("60.00"),
            entry_type="ORIGINAL",
        )
    )
    db_session.commit()

    resp = client.get("/api/v1/installer/earnings/summary?period=month")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["weekly_breakdown"]) == 1
    assert body["weekly_breakdown"][0]["total"] == "60.00"


def test_installer_workspace_returns_aggregates(
    installer_client_phase2,
    db_session,
    company_id,
    make_door_type,
):
    client, installer_id, _user = installer_client_phase2
    project = _make_project(company_id=company_id, name="Workspace", address="I")
    project.health_status = "AT_RISK"
    door_type = make_door_type(name="Workspace Door")
    db_session.add(project)
    db_session.flush()
    door = _make_door(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label="I-01",
        installer_id=installer_id,
        is_critical=True,
        status=DoorStatus.NOT_INSTALLED,
    )
    db_session.add(door)
    db_session.flush()
    event = CalendarEventORM(
        company_id=company_id,
        title="Today task",
        event_type=CalendarEventType.INSTALLATION,
        location="Workspace address",
        starts_at=datetime.now(timezone.utc) + timedelta(hours=1),
        ends_at=datetime.now(timezone.utc) + timedelta(hours=2),
        project_id=project.id,
        description=None,
    )
    db_session.add(event)
    db_session.flush()
    db_session.add(
        CalendarEventAssigneeORM(
            company_id=company_id,
            event_id=event.id,
            installer_id=installer_id,
        )
    )
    db_session.add(
        CompletedWorkORM(
            company_id=company_id,
            project_id=project.id,
            door_id=door.id,
            installer_id=installer_id,
            completed_at=datetime.now(timezone.utc),
            quantity=Decimal("1.00"),
            rate_snapshot=Decimal("25.00"),
            amount_snapshot=Decimal("25.00"),
            entry_type="ORIGINAL",
        )
    )
    db_session.commit()

    resp = client.get("/api/v1/installer/workspace")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["today_tasks"]) == 1
    assert len(body["priority_tasks"]) == 1
    assert len(body["problem_projects"]) == 1
    assert body["earnings_today"] == "25.00"


def test_installer_workspace_does_not_leak_other_installer_data(
    installer_client_phase2,
    db_session,
    company_id,
    make_door_type,
    make_installer,
):
    client, installer_id, _user = installer_client_phase2
    other_installer = make_installer(full_name="Other workspace", phone="+972500000888")
    project_mine = _make_project(company_id=company_id, name="Mine", address="L1")
    project_mine.health_status = "AT_RISK"
    project_other = _make_project(company_id=company_id, name="Other", address="L2")
    project_other.health_status = "AT_RISK"
    door_type = make_door_type(name="Workspace Leakage Door")
    db_session.add_all([project_mine, project_other])
    db_session.flush()
    my_door = _make_door(
        company_id=company_id,
        project_id=project_mine.id,
        door_type_id=door_type.id,
        unit_label="L-01",
        installer_id=installer_id,
        is_critical=True,
    )
    other_door = _make_door(
        company_id=company_id,
        project_id=project_other.id,
        door_type_id=door_type.id,
        unit_label="L-02",
        installer_id=other_installer.id,
        is_critical=True,
    )
    db_session.add_all([my_door, other_door])
    db_session.flush()
    my_event = CalendarEventORM(
        company_id=company_id,
        title="Mine",
        event_type=CalendarEventType.INSTALLATION,
        location="Mine",
        starts_at=datetime.now(timezone.utc) + timedelta(hours=1),
        ends_at=datetime.now(timezone.utc) + timedelta(hours=2),
        project_id=project_mine.id,
    )
    other_event = CalendarEventORM(
        company_id=company_id,
        title="Other",
        event_type=CalendarEventType.INSTALLATION,
        location="Other",
        starts_at=datetime.now(timezone.utc) + timedelta(hours=1),
        ends_at=datetime.now(timezone.utc) + timedelta(hours=2),
        project_id=project_other.id,
    )
    db_session.add_all([my_event, other_event])
    db_session.flush()
    db_session.add_all(
        [
            CalendarEventAssigneeORM(company_id=company_id, event_id=my_event.id, installer_id=installer_id),
            CalendarEventAssigneeORM(company_id=company_id, event_id=other_event.id, installer_id=other_installer.id),
        ]
    )
    db_session.commit()

    resp = client.get("/api/v1/installer/workspace")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [row["title"] for row in body["today_tasks"]] == ["Mine"]
    assert [row["project_id"] for row in body["problem_projects"]] == [str(project_mine.id)]
