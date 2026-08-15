from __future__ import annotations

import app.main as main_module


def test_health_returns_request_id_header(client_raw):
    response = client_raw.get("/health")

    assert response.status_code == 200
    assert response.headers.get("X-Request-ID")


def test_request_id_is_echoed_when_provided(client_raw):
    response = client_raw.get("/health", headers={"X-Request-ID": "req-123"})

    assert response.status_code == 200
    assert response.headers.get("X-Request-ID") == "req-123"


def test_readiness_checks_database(client_raw):
    response = client_raw.get("/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "checks": {"database": "ready"},
    }
    assert response.headers.get("X-Request-ID")


def test_readiness_returns_503_without_exposing_database_error(
    client_raw,
    monkeypatch,
):
    class UnavailableEngine:
        def connect(self):
            raise RuntimeError("sensitive-database-detail")

    monkeypatch.setattr(main_module, "engine", UnavailableEngine())

    response = client_raw.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {"database": "unavailable"},
    }
    assert "sensitive-database-detail" not in response.text
    assert response.headers.get("X-Request-ID")
