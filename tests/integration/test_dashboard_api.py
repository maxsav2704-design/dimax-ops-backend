from __future__ import annotations


def test_admin_dashboard_returns_sync_health_payload(client_admin_real_uow):
    resp = client_admin_real_uow.get("/api/v1/admin/dashboard")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "sync_health" in body
    assert "limits" in body
    assert "limit_alerts_unread_count" in body
    assert isinstance(body["sync_health"], dict)
    assert isinstance(body["limits"], dict)
    assert isinstance(body["limit_alerts_unread_count"], int)
    assert "counts" in body["sync_health"]
    assert "users" in body["limits"]
    assert "admin_users" in body["limits"]


def test_admin_dashboard_forbidden_for_installer_role(client_installer):
    resp = client_installer.get("/api/v1/admin/dashboard")
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "FORBIDDEN_SCOPE"


def test_admin_dashboard_get_is_read_only_until_the_health_run(
    client_admin_real_uow, db_session, company_id, make_installer,
):
    from app.modules.sync.infrastructure.models import InstallerSyncStateORM

    installer = make_installer(full_name="Dashboard Health Installer")
    state = InstallerSyncStateORM(
        company_id=company_id, installer_id=installer.id, last_cursor_ack=0, last_seen_at=None,
    )
    db_session.add(state)
    db_session.commit()

    resp = client_admin_real_uow.get("/api/v1/admin/dashboard")
    assert resp.status_code == 200, resp.text
    assert resp.json()["sync_health"]["counts"]["total"] >= 1
    db_session.refresh(state)
    assert state.health_days_offline is None  # a GET evaluated, but wrote nothing

    run = client_admin_real_uow.post("/api/v1/admin/sync/health/run")
    assert run.status_code == 200, run.text
    db_session.refresh(state)
    assert state.health_days_offline == 999999
