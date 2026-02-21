from __future__ import annotations


def test_admin_dashboard_returns_sync_health_payload(client_admin_real_uow):
    resp = client_admin_real_uow.get("/api/v1/admin/dashboard")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "sync_health" in body
    assert isinstance(body["sync_health"], dict)
    assert "counts" in body["sync_health"]


def test_admin_dashboard_forbidden_for_installer_role(client_installer):
    resp = client_installer.get("/api/v1/admin/dashboard")
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "FORBIDDEN"
