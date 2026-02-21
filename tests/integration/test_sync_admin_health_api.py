from __future__ import annotations


def test_sync_admin_health_run_and_summary_payload(client_admin_real_uow):
    run_resp = client_admin_real_uow.post("/api/v1/admin/sync/health/run")
    assert run_resp.status_code == 200, run_resp.text
    run_body = run_resp.json()
    assert run_body["ok"] is True
    assert "data" in run_body
    assert "counts" in run_body["data"]

    summary_resp = client_admin_real_uow.get("/api/v1/admin/sync/health/summary")
    assert summary_resp.status_code == 200, summary_resp.text
    summary_body = summary_resp.json()
    for key in ("max_cursor", "counts", "alerts_sent", "top_laggers", "top_offline"):
        assert key in summary_body


def test_sync_admin_health_forbidden_for_installer(client_installer):
    run_resp = client_installer.post("/api/v1/admin/sync/health/run")
    assert run_resp.status_code == 403, run_resp.text
    assert run_resp.json()["error"]["code"] == "FORBIDDEN"

    summary_resp = client_installer.get("/api/v1/admin/sync/health/summary")
    assert summary_resp.status_code == 403, summary_resp.text
    assert summary_resp.json()["error"]["code"] == "FORBIDDEN"
