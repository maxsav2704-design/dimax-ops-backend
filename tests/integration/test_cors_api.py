from __future__ import annotations


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
