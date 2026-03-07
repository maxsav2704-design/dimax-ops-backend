from __future__ import annotations


def test_health_returns_request_id_header(client_raw):
    response = client_raw.get("/health")

    assert response.status_code == 200
    assert response.headers.get("X-Request-ID")


def test_request_id_is_echoed_when_provided(client_raw):
    response = client_raw.get("/health", headers={"X-Request-ID": "req-123"})

    assert response.status_code == 200
    assert response.headers.get("X-Request-ID") == "req-123"
