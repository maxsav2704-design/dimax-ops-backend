from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.modules.calendar.infrastructure.models import CalendarEventAssigneeORM, CalendarEventORM
from app.modules.identity.infrastructure.models import CompanyORM


@pytest.mark.parametrize("unavailable", ["foreign", "missing", "inactive"])
def test_calendar_rejects_unavailable_assignees_without_partial_updates(
    client_admin_real_uow, db_session, company_id, make_installer, unavailable,
):
    own = make_installer()
    foreign_company = CompanyORM(id=uuid4(), name="Calendar boundary fixture", is_active=True)
    db_session.add(foreign_company)
    db_session.commit()
    foreign = make_installer(company=foreign_company.id)
    inactive = make_installer(is_active=False)
    bad_id = {"foreign": foreign.id, "missing": uuid4(), "inactive": inactive.id}[unavailable]
    start = datetime.now(timezone.utc)
    body = {"title": "QA assignment", "event_type": "installation", "starts_at": start.isoformat(),
            "ends_at": (start + timedelta(hours=1)).isoformat(), "installer_ids": [str(own.id)]}
    try:
        created = client_admin_real_uow.post("/api/v1/admin/calendar/events", json=body)
        assert created.status_code == 200, created.text
        event_id = created.json()["id"]
        changed = client_admin_real_uow.patch(f"/api/v1/admin/calendar/events/{event_id}",
            json={"title": "Must roll back", "installer_ids": [str(own.id), str(bad_id)]})
        assert changed.status_code == 404, changed.text
        rejected = client_admin_real_uow.post("/api/v1/admin/calendar/events",
            json={**body, "installer_ids": [str(bad_id)]})
        assert rejected.status_code == 404, rejected.text
        assert changed.json() == rejected.json()
        db_session.expire_all()
        events = db_session.query(CalendarEventORM).filter_by(company_id=company_id).all()
        assert len(events) == 1 and events[0].title == body["title"]
        assignees = db_session.query(CalendarEventAssigneeORM).filter_by(company_id=company_id).all()
        assert [row.installer_id for row in assignees] == [own.id]
    finally:
        db_session.rollback()
        db_session.delete(foreign)
        db_session.delete(foreign_company)
        db_session.commit()
