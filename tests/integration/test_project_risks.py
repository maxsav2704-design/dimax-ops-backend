from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.issues.infrastructure.models import IssueORM
from app.modules.projects.domain.enums import ProjectStatus
from app.modules.projects.infrastructure.models import ProjectORM
from app.modules.projects.infrastructure.risk_models import ProjectRiskORM
from app.modules.sync.infrastructure.models import InstallerSyncStateORM


def test_sync_danger_opens_a_project_risk_and_recovery_closes_it(
    client_admin_real_uow, db_session, company_id, make_installer, make_door_type,
):
    installer = make_installer(full_name="Offline Installer")
    project = ProjectORM(company_id=company_id, name=f"Risky {uuid.uuid4().hex[:6]}", address="Street 9", status=ProjectStatus.OK)
    db_session.add(project)
    db_session.flush()
    db_session.add(DoorORM(
        company_id=company_id, project_id=project.id, door_type_id=make_door_type().id, unit_label="R-01",
        our_price=Decimal("100.00"), status=DoorStatus.NOT_INSTALLED, installer_id=installer.id,
        reason_id=None, comment=None, installed_at=None, is_locked=False,
    ))
    state = InstallerSyncStateORM(company_id=company_id, installer_id=installer.id, last_cursor_ack=0, last_seen_at=None)
    db_session.add(state)
    db_session.commit()

    run = client_admin_real_uow.post("/api/v1/admin/sync/health/run")
    assert run.status_code == 200, run.text

    risks = db_session.query(ProjectRiskORM).filter(ProjectRiskORM.company_id == company_id, ProjectRiskORM.project_id == project.id).all()
    assert [(risk.kind, risk.status) for risk in risks] == [("SYNC", "OPEN")]
    assert db_session.query(IssueORM).filter(IssueORM.company_id == company_id).count() == 0

    detail = client_admin_real_uow.get(f"/api/v1/admin/projects/{project.id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["health_status"] == "AT_RISK"
    assert [risk["kind"] for risk in detail.json()["open_risks"]] == ["SYNC"]

    # A stale health (e.g. a risk moved by a migration) is repaired by the next run.
    db_session.refresh(project)
    project.health_status = "NORMAL"
    db_session.commit()
    assert client_admin_real_uow.post("/api/v1/admin/sync/health/run").status_code == 200
    assert client_admin_real_uow.get(f"/api/v1/admin/projects/{project.id}").json()["health_status"] == "AT_RISK"

    # The installer is back online and up to date: the risk closes, the project is normal again.
    db_session.refresh(state)
    state.last_seen_at = datetime.now(timezone.utc)
    db_session.commit()
    run = client_admin_real_uow.post("/api/v1/admin/sync/health/run")
    assert run.status_code == 200, run.text
    db_session.expire_all()
    risk = db_session.query(ProjectRiskORM).filter(ProjectRiskORM.project_id == project.id).one()
    assert risk.status == "CLOSED" and risk.closed_at is not None
    detail = client_admin_real_uow.get(f"/api/v1/admin/projects/{project.id}")
    assert detail.json()["health_status"] == "NORMAL"
    assert detail.json()["open_risks"] == []
