from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


def test_cors_preflight_allows_admin_origin(client_raw):
    resp = client_raw.options(
        "/api/v1/auth/login",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert resp.status_code in (200, 204), resp.text
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_cors_preflight_blocks_unknown_origin(client_raw):
    resp = client_raw.options(
        "/api/v1/auth/login",
        headers={
            "Origin": "http://evil.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert resp.headers.get("access-control-allow-origin") is None


@pytest.mark.parametrize("origin", ["http://localhost:5173", "http://evil.example"])
def test_unhandled_error_keeps_cors_boundary_and_safe_response(origin):
    app = create_app()

    @app.get("/_test/cors-failure")
    def fail():
        raise RuntimeError("private-database-details")

    with TestClient(app) as client:
        response = client.get("/_test/cors-failure", headers={"Origin": origin})

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "private-database-details" not in response.text
    assert response.headers.get("X-Request-ID")
    if origin == "http://localhost:5173":
        assert response.headers.get("access-control-allow-origin") == origin
        assert response.headers.get("access-control-allow-credentials") == "true"
        assert "X-Request-ID" in response.headers.get("access-control-expose-headers", "")
    else:
        assert response.headers.get("access-control-allow-origin") is None


def test_unauthenticated_api_response_is_readable_by_admin_origin(client_raw):
    response = client_raw.get(
        "/api/v1/admin/projects", headers={"Origin": "http://localhost:5173"},
    )
    assert response.status_code == 401
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert response.headers.get("X-Request-ID")
