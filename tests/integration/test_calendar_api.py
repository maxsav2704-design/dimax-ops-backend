from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.v1.acl import get_current_installer_id
from app.api.v1.deps import CurrentUser, require_installer
from app.main import create_app
from app.modules.calendar.domain.enums import CalendarEventType
from app.modules.calendar.infrastructure.models import (
    CalendarEventAssigneeORM,
    CalendarEventORM,
)
from app.modules.identity.infrastructure.models import CompanyORM
from app.modules.installers.infrastructure.models import InstallerORM
from app.modules.projects.domain.enums import ProjectStatus
from app.modules.projects.infrastructure.models import ProjectORM


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _create_project(db_session, *, company_id: uuid.UUID, name: str) -> ProjectORM:
    row = ProjectORM(
        company_id=company_id,
        name=name,
        address=f"{name} address",
        status=ProjectStatus.OK,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


@pytest.fixture()
def client_installer_calendar(installer_user: CurrentUser, db_session):
    installer = InstallerORM(
        company_id=installer_user.company_id,
        full_name="Installer Calendar",
        phone=f"+1888{uuid.uuid4().hex[:8]}",
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
        yield test_client, installer.id

    app.dependency_overrides.clear()


def test_admin_calendar_crud_and_filters(
    client_admin_real_uow,
    db_session,
    company_id,
    make_installer,
):
    starts = datetime.now(timezone.utc).replace(microsecond=0)
    ends = starts + timedelta(hours=2)

    project = _create_project(
        db_session,
        company_id=company_id,
        name=f"Calendar Project {uuid.uuid4().hex[:8]}",
    )
    installer_a = make_installer(full_name="Calendar A", phone="+10000004001")
    installer_b = make_installer(full_name="Calendar B", phone="+10000004002")

    create_a = client_admin_real_uow.post(
        "/api/v1/admin/calendar/events",
        json={
            "title": "Install A",
            "event_type": "installation",
            "starts_at": _iso(starts),
            "ends_at": _iso(ends),
            "project_id": str(project.id),
            "installer_ids": [str(installer_a.id)],
        },
    )
    assert create_a.status_code == 200, create_a.text
    event_a_id = create_a.json()["id"]

    create_b = client_admin_real_uow.post(
        "/api/v1/admin/calendar/events",
        json={
            "title": "Meeting B",
            "event_type": "meeting",
            "starts_at": _iso(starts + timedelta(hours=4)),
            "ends_at": _iso(ends + timedelta(hours=4)),
            "installer_ids": [str(installer_b.id)],
        },
    )
    assert create_b.status_code == 200, create_b.text

    base_q = f"starts_at={_iso(starts - timedelta(hours=1))}&ends_at={_iso(ends + timedelta(hours=5))}"
    list_resp = client_admin_real_uow.get(f"/api/v1/admin/calendar/events?{base_q}")
    assert list_resp.status_code == 200, list_resp.text
    ids = {x["id"] for x in list_resp.json()["items"]}
    assert event_a_id in ids

    by_installer_resp = client_admin_real_uow.get(
        f"/api/v1/admin/calendar/events?{base_q}&installer_id={installer_a.id}"
    )
    assert by_installer_resp.status_code == 200, by_installer_resp.text
    installer_items = by_installer_resp.json()["items"]
    assert len(installer_items) == 1
    assert installer_items[0]["id"] == event_a_id

    by_project_resp = client_admin_real_uow.get(
        f"/api/v1/admin/calendar/events?{base_q}&project_id={project.id}"
    )
    assert by_project_resp.status_code == 200, by_project_resp.text
    assert any(x["id"] == event_a_id for x in by_project_resp.json()["items"])

    by_type_resp = client_admin_real_uow.get(
        f"/api/v1/admin/calendar/events?{base_q}&event_type=installation"
    )
    assert by_type_resp.status_code == 200, by_type_resp.text
    assert all(x["event_type"] == "installation" for x in by_type_resp.json()["items"])

    patch_resp = client_admin_real_uow.patch(
        f"/api/v1/admin/calendar/events/{event_a_id}",
        json={
            "title": "Install A Updated",
            "installer_ids": [str(installer_b.id)],
        },
    )
    assert patch_resp.status_code == 200, patch_resp.text
    assert patch_resp.json()["ok"] is True

    by_old_installer_resp = client_admin_real_uow.get(
        f"/api/v1/admin/calendar/events?{base_q}&installer_id={installer_a.id}"
    )
    assert by_old_installer_resp.status_code == 200, by_old_installer_resp.text
    assert all(x["id"] != event_a_id for x in by_old_installer_resp.json()["items"])

    delete_resp = client_admin_real_uow.delete(
        f"/api/v1/admin/calendar/events/{event_a_id}"
    )
    assert delete_resp.status_code == 200, delete_resp.text
    assert delete_resp.json()["ok"] is True

    list_after_delete_resp = client_admin_real_uow.get(
        f"/api/v1/admin/calendar/events?{base_q}"
    )
    assert list_after_delete_resp.status_code == 200, list_after_delete_resp.text
    assert all(
        x["id"] != event_a_id for x in list_after_delete_resp.json()["items"]
    )


def test_installer_calendar_lists_only_assigned_events(
    client_admin_real_uow,
    client_installer_calendar,
    db_session,
    company_id,
    make_installer,
):
    client_installer, installer_id = client_installer_calendar
    other_installer = make_installer(full_name="Other Installer", phone="+10000004003")

    starts = datetime.now(timezone.utc).replace(microsecond=0)
    ends = starts + timedelta(hours=1)
    q = f"starts_at={_iso(starts - timedelta(hours=1))}&ends_at={_iso(ends + timedelta(hours=2))}"

    create_my = client_admin_real_uow.post(
        "/api/v1/admin/calendar/events",
        json={
            "title": "My Event",
            "event_type": "delivery",
            "starts_at": _iso(starts),
            "ends_at": _iso(ends),
            "installer_ids": [str(installer_id)],
        },
    )
    assert create_my.status_code == 200, create_my.text
    my_event_id = create_my.json()["id"]

    create_other = client_admin_real_uow.post(
        "/api/v1/admin/calendar/events",
        json={
            "title": "Other Event",
            "event_type": "meeting",
            "starts_at": _iso(starts),
            "ends_at": _iso(ends),
            "installer_ids": [str(other_installer.id)],
        },
    )
    assert create_other.status_code == 200, create_other.text

    list_resp = client_installer.get(f"/api/v1/installer/calendar/events?{q}")
    assert list_resp.status_code == 200, list_resp.text
    items = list_resp.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == my_event_id


def test_calendar_admin_forbidden_for_installer_role(client_installer):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    q = f"starts_at={_iso(now)}&ends_at={_iso(now + timedelta(hours=1))}"
    resp = client_installer.get(f"/api/v1/admin/calendar/events?{q}")
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "FORBIDDEN"


def test_calendar_validation_and_not_found(client_admin_real_uow):
    now = datetime.now(timezone.utc).replace(microsecond=0)

    invalid_time_resp = client_admin_real_uow.post(
        "/api/v1/admin/calendar/events",
        json={
            "title": "Bad Event",
            "event_type": "installation",
            "starts_at": _iso(now + timedelta(hours=2)),
            "ends_at": _iso(now + timedelta(hours=1)),
            "installer_ids": [],
        },
    )
    assert invalid_time_resp.status_code == 422, invalid_time_resp.text
    assert invalid_time_resp.json()["error"]["code"] == "VALIDATION_ERROR"

    invalid_type_resp = client_admin_real_uow.post(
        "/api/v1/admin/calendar/events",
        json={
            "title": "Bad Type",
            "event_type": "random",
            "starts_at": _iso(now),
            "ends_at": _iso(now + timedelta(hours=1)),
            "installer_ids": [],
        },
    )
    assert invalid_type_resp.status_code == 422, invalid_type_resp.text

    missing_event_id = uuid.uuid4()
    patch_resp = client_admin_real_uow.patch(
        f"/api/v1/admin/calendar/events/{missing_event_id}",
        json={"title": "Nope"},
    )
    assert patch_resp.status_code == 404, patch_resp.text
    assert patch_resp.json()["error"]["code"] == "NOT_FOUND"

    delete_resp = client_admin_real_uow.delete(
        f"/api/v1/admin/calendar/events/{missing_event_id}"
    )
    assert delete_resp.status_code == 404, delete_resp.text
    assert delete_resp.json()["error"]["code"] == "NOT_FOUND"


def test_calendar_multi_tenant_isolation(client_admin_real_uow, db_session):
    foreign_company_id = uuid.uuid4()
    foreign_project_id = uuid.uuid4()
    foreign_installer_id = uuid.uuid4()
    foreign_event_id = uuid.uuid4()

    starts = datetime.now(timezone.utc).replace(microsecond=0)
    ends = starts + timedelta(hours=1)
    q = f"starts_at={_iso(starts - timedelta(hours=1))}&ends_at={_iso(ends + timedelta(hours=1))}"

    db_session.add(
        CompanyORM(
            id=foreign_company_id,
            name=f"Foreign {foreign_company_id}",
            is_active=True,
        )
    )
    db_session.add(
        ProjectORM(
            id=foreign_project_id,
            company_id=foreign_company_id,
            name="Foreign Project",
            address="Foreign Address",
            status=ProjectStatus.OK,
        )
    )
    db_session.add(
        InstallerORM(
            id=foreign_installer_id,
            company_id=foreign_company_id,
            full_name="Foreign Installer",
            phone="+19990000001",
            email=None,
            address=None,
            passport_id=None,
            notes=None,
            status="ACTIVE",
            is_active=True,
            user_id=None,
        )
    )
    db_session.commit()

    db_session.add(
        CalendarEventORM(
            id=foreign_event_id,
            company_id=foreign_company_id,
            title="Foreign Event",
            event_type=CalendarEventType.INSTALLATION,
            starts_at=starts,
            ends_at=ends,
            location=None,
            description=None,
            project_id=foreign_project_id,
        )
    )
    db_session.commit()

    db_session.add(
        CalendarEventAssigneeORM(
            company_id=foreign_company_id,
            event_id=foreign_event_id,
            installer_id=foreign_installer_id,
        )
    )
    db_session.commit()

    try:
        list_resp = client_admin_real_uow.get(f"/api/v1/admin/calendar/events?{q}")
        assert list_resp.status_code == 200, list_resp.text
        assert all(x["id"] != str(foreign_event_id) for x in list_resp.json()["items"])

        patch_resp = client_admin_real_uow.patch(
            f"/api/v1/admin/calendar/events/{foreign_event_id}",
            json={"title": "Updated"},
        )
        assert patch_resp.status_code == 404, patch_resp.text

        delete_resp = client_admin_real_uow.delete(
            f"/api/v1/admin/calendar/events/{foreign_event_id}"
        )
        assert delete_resp.status_code == 404, delete_resp.text
    finally:
        db_session.rollback()
        db_session.execute(
            text("DELETE FROM calendar_event_assignees WHERE company_id = :cid"),
            {"cid": foreign_company_id},
        )
        db_session.execute(
            text("DELETE FROM calendar_events WHERE company_id = :cid"),
            {"cid": foreign_company_id},
        )
        db_session.execute(
            text("DELETE FROM installers WHERE company_id = :cid"),
            {"cid": foreign_company_id},
        )
        db_session.execute(
            text("DELETE FROM projects WHERE company_id = :cid"),
            {"cid": foreign_company_id},
        )
        db_session.execute(
            text("DELETE FROM companies WHERE id = :cid"),
            {"cid": foreign_company_id},
        )
        db_session.commit()
