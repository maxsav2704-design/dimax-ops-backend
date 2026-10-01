from decimal import Decimal
import uuid

import pytest

from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.earnings.infrastructure.models import CompletedWorkORM
from app.modules.issues.infrastructure.models import IssueORM
from app.modules.projects.infrastructure.models import ProjectORM
from app.modules.sync.domain.enums import SyncChangeType
from app.shared.infrastructure.db.uow_sqlalchemy import SqlAlchemyUnitOfWork


@pytest.fixture()
def issue_case(db_session, company_id, installer_user, make_installer, make_door_type):
    installer = make_installer()
    installer.user_id = installer_user.id
    project = ProjectORM(company_id=company_id, name="Issue lifecycle", address="Test site")
    db_session.add(project)
    db_session.flush()
    door = DoorORM(
        company_id=company_id, project_id=project.id, door_type_id=make_door_type().id,
        unit_label="ISSUE-201", our_price=Decimal("1000"), installer_id=installer.id,
        installer_rate_snapshot=Decimal("250"), status=DoorStatus.NOT_INSTALLED,
        version=0, is_locked=False,
    )
    db_session.add(door)
    db_session.commit()
    with SqlAlchemyUnitOfWork() as uow:
        uow.sync_change_log.add_change(
            company_id=company_id, change_type=SyncChangeType.PROJECT_BASE,
            entity_id=project.id, project_id=project.id, installer_id=installer.id,
            payload={"id": str(project.id), "name": project.name},
        )
    return door, project, installer


def _sync(client, cursor=0, events=None, headers=None):
    response = client.post("/api/v1/installer/sync", headers=headers, json={
        "since_cursor": cursor, "ack_cursor": cursor, "device_id": "issue-lifecycle-test",
        "events": events or [],
    })
    assert response.status_code == 200, response.text
    return response.json()


def _report(client, door, cursor):
    return _sync(client, cursor, [{
        "client_event_id": f"issue-{uuid.uuid4()}", "type": "ISSUE_CREATE",
        "project_id": str(door.project_id),
        "payload": {"door_id": str(door.id), "title": "Access blocked", "details": "Acceptance only"},
    }])


def test_incremental_issue_create_and_close_reach_phone(
    issue_case, client_installer, client_admin_real_uow, db_session,
):
    door, _, _ = issue_case
    first = _sync(client_installer)
    created = _report(client_installer, door, first["next_cursor"])
    assert created["acks"][0]["ok"] is True
    assert created["reset_required"] is False
    changes = [row["payload"] for row in created["changes"] if row["change_type"] == "ISSUE"]
    assert len(changes) == 1
    assert changes[0]["door_id"] == str(door.id) and changes[0]["status"] == "OPEN"
    issue_id = changes[0]["id"]
    response = client_admin_real_uow.patch(f"/api/v1/admin/issues/{issue_id}/status", json={"status": "CLOSED"})
    assert response.status_code == 200, response.text
    closed = _sync(client_installer, created["next_cursor"])
    assert any(row["change_type"] == "ISSUE" and row["payload"]["status"] == "CLOSED" for row in closed["changes"])
    assert any(row["change_type"] == "PROJECT_BASE" and row["payload"].get("health_status") == "NORMAL" for row in closed["changes"])
    cold = _sync(client_installer)
    assert any(row["id"] == issue_id and row["status"] == "CLOSED" for row in cold["snapshot"]["issues"])
    assert db_session.query(CompletedWorkORM).filter_by(door_id=door.id).count() == 0


@pytest.mark.parametrize("initial", [DoorStatus.NOT_INSTALLED, DoorStatus.IN_PROGRESS])
@pytest.mark.parametrize("endpoint", ["status", "workflow", "bulk"])
def test_closing_issue_restores_noncompleted_state_without_accrual(
    issue_case, client_installer, client_admin_real_uow, db_session, initial, endpoint,
):
    door, project, _ = issue_case
    door.status = initial
    db_session.commit()
    _report(client_installer, door, 0)
    issue = db_session.query(IssueORM).filter_by(door_id=door.id).one()
    url = f"/api/v1/admin/issues/{issue.id}/{endpoint}"
    body = {"status": "CLOSED"} if endpoint == "status" else {"workflow_state": "CLOSED"}
    if endpoint == "bulk":
        url = "/api/v1/admin/issues/workflow/bulk"
        body["issue_ids"] = [str(issue.id)]
    response = client_admin_real_uow.patch(url, json=body)
    assert response.status_code == 200, response.text
    db_session.refresh(door)
    db_session.refresh(project)
    assert door.status == initial
    assert not door.is_locked and door.installed_at is None
    assert project.health_status == "NORMAL"
    assert db_session.query(CompletedWorkORM).filter_by(door_id=door.id).count() == 0


def test_issue_on_completed_door_preserves_completion_and_payroll(
    issue_case, client_installer, client_admin_real_uow, db_session,
):
    door, _, _ = issue_case
    installed = _sync(client_installer, events=[{
        "client_event_id": "install-before-issue", "type": "DOOR_SET_STATUS",
        "project_id": str(door.project_id),
        "payload": {"door_id": str(door.id), "status": "INSTALLED", "previous_version": 0},
    }])
    assert installed["acks"][0]["ok"] is True
    db_session.refresh(door)
    completed_at = door.installed_at
    _report(client_installer, door, installed["next_cursor"])
    db_session.refresh(door)
    assert door.status == DoorStatus.INSTALLED and door.is_locked
    issue = db_session.query(IssueORM).filter_by(door_id=door.id).one()
    response = client_admin_real_uow.patch(f"/api/v1/admin/issues/{issue.id}/workflow", json={"workflow_state": "CLOSED"})
    assert response.status_code == 200, response.text
    db_session.refresh(door)
    work = db_session.query(CompletedWorkORM).filter_by(door_id=door.id).one()
    assert door.installed_at == completed_at and work.amount_snapshot == Decimal("250")
    assert door.status == DoorStatus.INSTALLED and door.is_locked


@pytest.mark.parametrize("status,workflow", [("OPEN", "CLOSED"), ("CLOSED", "IN_PROGRESS")])
def test_issue_rejects_contradictory_closed_state(
    issue_case, client_installer, client_admin_real_uow, db_session, status, workflow,
):
    door, _, _ = issue_case
    _report(client_installer, door, 0)
    issue = db_session.query(IssueORM).filter_by(door_id=door.id).one()
    response = client_admin_real_uow.patch(f"/api/v1/admin/issues/{issue.id}/workflow", json={
        "status": status, "workflow_state": workflow,
    })
    assert response.status_code == 422, response.text
    db_session.refresh(issue)
    assert issue.status.value == "OPEN" and issue.workflow_state.value == "NEW"


def test_issue_reassignment_hides_old_events_and_delivers_to_new_installer(
    issue_case, client_installer, client_admin_real_uow, client_raw, db_session,
    make_installer, make_user,
):
    door, project, installer = issue_case
    other_user = make_user(password="Issue-reassignment-test-2026!")
    other = make_installer(full_name="Other issue installer")
    other.user_id = other_user.id
    remaining = DoorORM(
        company_id=door.company_id, project_id=project.id, door_type_id=door.door_type_id,
        unit_label="REMAINING", our_price=Decimal("100"), installer_id=installer.id,
        status=DoorStatus.NOT_INSTALLED, is_locked=False,
    )
    db_session.add(remaining)
    db_session.commit()
    before = _sync(client_installer)["next_cursor"]
    _report(client_installer, door, before)
    assigned = client_admin_real_uow.post(f"/api/v1/admin/projects/doors/{door.id}/assign-installer", json={"installer_id": str(other.id)})
    assert assigned.status_code == 200, assigned.text
    old = _sync(client_installer, before)
    assert not any(row["change_type"] == "ISSUE" for row in old["changes"])
    login = client_raw.post("/api/v1/auth/login", json={
        "company_id": str(door.company_id), "email": other_user.email,
        "password": "Issue-reassignment-test-2026!", "device_id": "issue-new-installer",
    })
    assert login.status_code == 200, login.text
    new = _sync(client_raw, before, headers={"Authorization": f"Bearer {login.json()['access_token']}"})
    assert any(row["change_type"] == "ISSUE" and row["payload"]["door_id"] == str(door.id) for row in new["changes"])


def test_installing_reported_door_closes_issue_in_incremental_sync(
    issue_case, client_installer, db_session,
):
    door, _, _ = issue_case
    created = _report(client_installer, door, 0)
    installed = _sync(client_installer, created["next_cursor"], [{
        "client_event_id": "install-after-issue", "type": "DOOR_SET_STATUS",
        "project_id": str(door.project_id),
        "payload": {"door_id": str(door.id), "status": "INSTALLED", "previous_version": 1},
    }])
    assert installed["acks"][0]["ok"] is True
    assert any(row["change_type"] == "ISSUE" and row["payload"]["status"] == "CLOSED" for row in installed["changes"])
    issue = db_session.query(IssueORM).filter_by(door_id=door.id).one()
    assert issue.status.value == issue.workflow_state.value == "CLOSED"
    assert db_session.query(CompletedWorkORM).filter_by(door_id=door.id).count() == 1


def test_comment_refreshes_issue_closed_after_initial_read(
    issue_case, client_installer, client_admin_real_uow, db_session, installer_user,
):
    from app.modules.issues.application.installer_api_service import InstallerIssuesApiService

    door, _, installer = issue_case
    created = _report(client_installer, door, 0)
    issue = db_session.query(IssueORM).filter_by(door_id=door.id).one()
    with SqlAlchemyUnitOfWork() as uow:
        stale = uow.issues.get(company_id=door.company_id, issue_id=issue.id)
        assert stale.status.value == "OPEN"
        closed = client_admin_real_uow.patch(f"/api/v1/admin/issues/{issue.id}/status", json={"status": "CLOSED"})
        assert closed.status_code == 200, closed.text
        updated = InstallerIssuesApiService.update_issue_comment(
            uow, company_id=door.company_id, installer_id=installer.id,
            user_id=installer_user.id, issue_id=issue.id, comment="Access confirmed",
        )
        assert updated.status == "CLOSED"
    result = _sync(client_installer, created["next_cursor"])
    issues = [row["payload"] for row in result["changes"] if row["change_type"] == "ISSUE"]
    assert issues[-1]["status"] == "CLOSED" and issues[-1]["details"] == "Access confirmed"
