from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timedelta, timezone
import uuid

from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.issues.domain.enums import IssueStatus
from app.modules.issues.infrastructure.models import IssueORM
from app.modules.projects.infrastructure.models import ProjectORM


def _seed_issue(db_session, *, company_id, make_door_type):
    suffix = uuid.uuid4().hex[:8]
    project = ProjectORM(
        company_id=company_id,
        name=f"Issues Project {suffix}",
        address=f"Issues Address {suffix}",
    )
    db_session.add(project)
    db_session.flush()

    door_type = make_door_type(name="Issues Door Type")
    door = DoorORM(
        company_id=company_id,
        project_id=project.id,
        door_type_id=door_type.id,
        unit_label="A-101",
        our_price=Decimal("1000.00"),
        status=DoorStatus.NOT_INSTALLED,
    )
    db_session.add(door)
    db_session.flush()

    issue = IssueORM(
        company_id=company_id,
        door_id=door.id,
        status=IssueStatus.OPEN,
        title="Install blocked",
        details="Client requested delay",
    )
    db_session.add(issue)
    db_session.commit()
    return project, door, issue


def test_admin_issues_list_get_and_update_status(
    client_admin_real_uow,
    db_session,
    company_id,
    make_door_type,
):
    project, door, issue = _seed_issue(
        db_session,
        company_id=company_id,
        make_door_type=make_door_type,
    )

    list_resp = client_admin_real_uow.get("/api/v1/admin/issues?status=OPEN")
    assert list_resp.status_code == 200, list_resp.text
    list_items = list_resp.json()["items"]
    assert any(x["id"] == str(issue.id) for x in list_items)

    row = next(x for x in list_items if x["id"] == str(issue.id))
    assert row["project_id"] == str(project.id)
    assert row["door_id"] == str(door.id)
    assert row["door_unit_label"] == "A-101"
    assert row["status"] == "OPEN"
    assert row["workflow_state"] == "NEW"
    assert row["priority"] == "P3"
    assert row["owner_user_id"] is None
    assert row["due_at"] is None
    assert row["is_overdue"] is False

    get_resp = client_admin_real_uow.get(f"/api/v1/admin/issues/{issue.id}")
    assert get_resp.status_code == 200, get_resp.text
    assert get_resp.json()["id"] == str(issue.id)

    comments_resp = client_admin_real_uow.get(
        f"/api/v1/admin/issues/{issue.id}/comments"
    )
    assert comments_resp.status_code == 200, comments_resp.text
    assert comments_resp.json() == {"items": []}

    media_resp = client_admin_real_uow.get(f"/api/v1/admin/issues/{issue.id}/media")
    assert media_resp.status_code == 200, media_resp.text
    assert media_resp.json() == {"items": []}

    patch_resp = client_admin_real_uow.patch(
        f"/api/v1/admin/issues/{issue.id}/status",
        json={"status": "CLOSED", "details": "Resolved by admin"},
    )
    assert patch_resp.status_code == 200, patch_resp.text
    assert patch_resp.json()["status"] == "CLOSED"
    assert patch_resp.json()["details"] == "Resolved by admin"

    closed_list = client_admin_real_uow.get("/api/v1/admin/issues?status=CLOSED")
    assert closed_list.status_code == 200, closed_list.text
    assert any(x["id"] == str(issue.id) for x in closed_list.json()["items"])


def test_admin_issue_workflow_assignment_and_filters(
    client_admin_real_uow,
    db_session,
    company_id,
    make_door_type,
    admin_user,
):
    _project, _door, issue = _seed_issue(
        db_session,
        company_id=company_id,
        make_door_type=make_door_type,
    )

    due_at = (datetime.now(timezone.utc) - timedelta(hours=2)).replace(microsecond=0)
    patch_resp = client_admin_real_uow.patch(
        f"/api/v1/admin/issues/{issue.id}/workflow",
        json={
            "owner_user_id": str(admin_user.id),
            "priority": "P1",
            "workflow_state": "IN_PROGRESS",
            "due_at": due_at.isoformat().replace("+00:00", "Z"),
            "details": "Work started",
        },
    )
    assert patch_resp.status_code == 200, patch_resp.text
    body = patch_resp.json()
    assert body["id"] == str(issue.id)
    assert body["owner_user_id"] == str(admin_user.id)
    assert body["priority"] == "P1"
    assert body["workflow_state"] == "IN_PROGRESS"
    assert body["status"] == "OPEN"
    assert body["is_overdue"] is True
    assert body["details"] == "Work started"

    by_owner = client_admin_real_uow.get(
        f"/api/v1/admin/issues?owner_user_id={admin_user.id}"
    )
    assert by_owner.status_code == 200, by_owner.text
    assert any(x["id"] == str(issue.id) for x in by_owner.json()["items"])

    by_workflow = client_admin_real_uow.get(
        "/api/v1/admin/issues?workflow_state=IN_PROGRESS"
    )
    assert by_workflow.status_code == 200, by_workflow.text
    assert any(x["id"] == str(issue.id) for x in by_workflow.json()["items"])

    overdue = client_admin_real_uow.get("/api/v1/admin/issues?overdue_only=true")
    assert overdue.status_code == 200, overdue.text
    assert any(x["id"] == str(issue.id) for x in overdue.json()["items"])

    close_resp = client_admin_real_uow.patch(
        f"/api/v1/admin/issues/{issue.id}/workflow",
        json={"workflow_state": "CLOSED"},
    )
    assert close_resp.status_code == 200, close_resp.text
    assert close_resp.json()["status"] == "CLOSED"
    assert close_resp.json()["workflow_state"] == "CLOSED"
    assert close_resp.json()["is_overdue"] is False

    clear_owner_resp = client_admin_real_uow.patch(
        f"/api/v1/admin/issues/{issue.id}/workflow",
        json={
            "owner_user_id": None,
            "priority": "P4",
            "status": "OPEN",
            "workflow_state": "TRIAGED",
            "due_at": None,
        },
    )
    assert clear_owner_resp.status_code == 200, clear_owner_resp.text
    assert clear_owner_resp.json()["owner_user_id"] is None
    assert clear_owner_resp.json()["priority"] == "P4"
    assert clear_owner_resp.json()["status"] == "OPEN"
    assert clear_owner_resp.json()["workflow_state"] == "TRIAGED"
    assert clear_owner_resp.json()["due_at"] is None


def test_admin_issue_workflow_validation_errors(
    client_admin_real_uow,
    db_session,
    company_id,
    make_door_type,
):
    _project, _door, issue = _seed_issue(
        db_session,
        company_id=company_id,
        make_door_type=make_door_type,
    )

    empty_patch = client_admin_real_uow.patch(
        f"/api/v1/admin/issues/{issue.id}/workflow",
        json={},
    )
    assert empty_patch.status_code == 422, empty_patch.text
    assert empty_patch.json()["error"]["code"] == "VALIDATION_ERROR"

    bad_owner = client_admin_real_uow.patch(
        f"/api/v1/admin/issues/{issue.id}/workflow",
        json={"owner_user_id": str(uuid.uuid4())},
    )
    assert bad_owner.status_code == 422, bad_owner.text
    assert bad_owner.json()["error"]["code"] == "VALIDATION_ERROR"


def test_admin_issue_bulk_workflow_update(
    client_admin_real_uow,
    db_session,
    company_id,
    make_door_type,
    admin_user,
):
    _project, _door, issue1 = _seed_issue(
        db_session,
        company_id=company_id,
        make_door_type=make_door_type,
    )
    _project2, _door2, issue2 = _seed_issue(
        db_session,
        company_id=company_id,
        make_door_type=make_door_type,
    )

    due_at = (datetime.now(timezone.utc) + timedelta(days=1)).replace(microsecond=0)
    resp = client_admin_real_uow.patch(
        "/api/v1/admin/issues/workflow/bulk",
        json={
            "issue_ids": [str(issue1.id), str(issue2.id)],
            "owner_user_id": str(admin_user.id),
            "priority": "P2",
            "workflow_state": "IN_PROGRESS",
            "due_at": due_at.isoformat().replace("+00:00", "Z"),
            "details": "Bulk triage",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["updated"] == 2
    assert len(body["items"]) == 2
    ids = {x["id"] for x in body["items"]}
    assert ids == {str(issue1.id), str(issue2.id)}
    for row in body["items"]:
        assert row["owner_user_id"] == str(admin_user.id)
        assert row["priority"] == "P2"
        assert row["workflow_state"] == "IN_PROGRESS"
        assert row["status"] == "OPEN"
        assert row["details"] == "Bulk triage"


def test_admin_issue_bulk_workflow_validation_errors(
    client_admin_real_uow,
    db_session,
    company_id,
    make_door_type,
):
    _project, _door, issue = _seed_issue(
        db_session,
        company_id=company_id,
        make_door_type=make_door_type,
    )

    empty_patch = client_admin_real_uow.patch(
        "/api/v1/admin/issues/workflow/bulk",
        json={"issue_ids": [str(issue.id)]},
    )
    assert empty_patch.status_code == 422, empty_patch.text
    assert empty_patch.json()["error"]["code"] == "VALIDATION_ERROR"

    missing_issue = client_admin_real_uow.patch(
        "/api/v1/admin/issues/workflow/bulk",
        json={
            "issue_ids": [str(issue.id), str(uuid.uuid4())],
            "workflow_state": "TRIAGED",
        },
    )
    assert missing_issue.status_code == 200, missing_issue.text
    payload = missing_issue.json()
    assert payload["updated"] == 1
    assert len(payload["missing_issue_ids"]) == 1


def test_admin_door_action_with_malformed_id_is_a_validation_error(client_admin_real_uow):
    resp = client_admin_real_uow.post("/api/v1/admin/doors/not-a-uuid/install")
    assert resp.status_code == 422, resp.text


def test_public_journal_endpoints_are_rate_limited(client_admin_real_uow):
    token = uuid.uuid4().hex
    statuses = [client_admin_real_uow.get(f"/api/v1/public/journals/{token}").status_code for _ in range(61)]
    assert statuses[0] == 404
    assert statuses[-1] == 429


def test_admin_issues_returns_404_for_missing_issue(client_admin_real_uow):
    issue_id = uuid.uuid4()
    get_resp = client_admin_real_uow.get(f"/api/v1/admin/issues/{issue_id}")
    assert get_resp.status_code == 404, get_resp.text

    patch_resp = client_admin_real_uow.patch(
        f"/api/v1/admin/issues/{issue_id}/status",
        json={"status": "CLOSED"},
    )
    assert patch_resp.status_code == 404, patch_resp.text

    patch_workflow = client_admin_real_uow.patch(
        f"/api/v1/admin/issues/{issue_id}/workflow",
        json={"workflow_state": "TRIAGED"},
    )
    assert patch_workflow.status_code == 404, patch_workflow.text

    patch_bulk = client_admin_real_uow.patch(
        "/api/v1/admin/issues/workflow/bulk",
        json={
            "issue_ids": [str(issue_id)],
            "workflow_state": "TRIAGED",
        },
    )
    assert patch_bulk.status_code == 200, patch_bulk.text
    assert patch_bulk.json()["updated"] == 0
    assert patch_bulk.json()["missing_issue_ids"] == [str(issue_id)]


def test_admin_issues_forbidden_for_installer(client_installer):
    issue_id = uuid.uuid4()
    list_resp = client_installer.get("/api/v1/admin/issues")
    assert list_resp.status_code == 403, list_resp.text
    assert list_resp.json()["error"]["code"] == "FORBIDDEN_SCOPE"

    patch_resp = client_installer.patch(
        f"/api/v1/admin/issues/{issue_id}/status",
        json={"status": "CLOSED"},
    )
    assert patch_resp.status_code == 403, patch_resp.text
    assert patch_resp.json()["error"]["code"] == "FORBIDDEN_SCOPE"

    patch_workflow = client_installer.patch(
        f"/api/v1/admin/issues/{issue_id}/workflow",
        json={"workflow_state": "TRIAGED"},
    )
    assert patch_workflow.status_code == 403, patch_workflow.text
    assert patch_workflow.json()["error"]["code"] == "FORBIDDEN_SCOPE"

    patch_bulk = client_installer.patch(
        "/api/v1/admin/issues/workflow/bulk",
        json={
            "issue_ids": [str(issue_id)],
            "workflow_state": "TRIAGED",
        },
    )
    assert patch_bulk.status_code == 403, patch_bulk.text
    assert patch_bulk.json()["error"]["code"] == "FORBIDDEN_SCOPE"


def test_authenticated_media_url_returns_404_until_media_store_exists(client_installer):
    resp = client_installer.get(f"/api/v1/media/{uuid.uuid4()}/url")
    assert resp.status_code == 404, resp.text
    assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_system_risks_live_on_the_project_not_on_a_door(db_session, company_id, make_door_type):
    from app.modules.projects.infrastructure.risk_models import RISK_SYNC
    from app.modules.projects.infrastructure.risk_repository import ProjectRiskRepository

    project, door, issue = _seed_issue(db_session, company_id=company_id, make_door_type=make_door_type)
    repo = ProjectRiskRepository(db_session)

    risk_id, changed = repo.open_risk(company_id=company_id, project_id=project.id, kind=RISK_SYNC, details="offline")
    assert changed is True
    same_id, changed_again = repo.open_risk(company_id=company_id, project_id=project.id, kind=RISK_SYNC, details="offline 2")
    assert same_id == risk_id and changed_again is False
    assert [risk.details for risk in repo.list_open_by_project(company_id=company_id, project_id=project.id)] == ["offline 2"]
    # The door's real issue is untouched and the company still has exactly one issue.
    db_session.refresh(issue)
    assert issue.title == "Install blocked"
    assert db_session.query(IssueORM).filter(IssueORM.company_id == company_id).count() == 1

    closed_id, closed = repo.close_risk(company_id=company_id, project_id=project.id, kind=RISK_SYNC)
    assert closed_id == risk_id and closed is True
    assert repo.close_risk(company_id=company_id, project_id=project.id, kind=RISK_SYNC) == (risk_id, False)
    assert repo.list_open_by_project(company_id=company_id, project_id=project.id) == []


def test_issue_comment_thread_is_appended_by_office_and_installer(client_admin_real_uow, client_installer, db_session, company_id, make_door_type):
    project, door, issue = _seed_issue(db_session, company_id=company_id, make_door_type=make_door_type)

    empty = client_admin_real_uow.get(f"/api/v1/admin/issues/{issue.id}/comments")
    assert empty.status_code == 200 and empty.json()["items"] == [], empty.text

    created = client_admin_real_uow.post(f"/api/v1/admin/issues/{issue.id}/comments", json={"body": "Checked on site, waiting for the frame."})
    assert created.status_code == 201, created.text
    assert created.json()["body"] == "Checked on site, waiting for the frame."
    assert created.json()["author_name"]

    blank = client_admin_real_uow.post(f"/api/v1/admin/issues/{issue.id}/comments", json={"body": "   "})
    assert blank.status_code == 422, blank.text

    listed = client_admin_real_uow.get(f"/api/v1/admin/issues/{issue.id}/comments")
    assert listed.status_code == 200, listed.text
    assert [item["body"] for item in listed.json()["items"]] == ["Checked on site, waiting for the frame."]

    # The installer who does not see the issue cannot read or write its thread.
    foreign = client_installer.get(f"/api/v1/installer/issues/{issue.id}/comments")
    assert foreign.status_code in (403, 404), foreign.text
