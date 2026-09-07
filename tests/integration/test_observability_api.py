from __future__ import annotations

import json
import logging
import uuid

from fastapi.testclient import TestClient

import app.main as main_module


def test_health_returns_request_id_header(client_raw):
    response = client_raw.get("/health")

    assert response.status_code == 200
    assert response.headers.get("X-Request-ID")


def test_request_id_is_echoed_when_provided(client_raw):
    response = client_raw.get("/health", headers={"X-Request-ID": "req-123"})

    assert response.status_code == 200
    assert response.headers.get("X-Request-ID") == "req-123"


def test_invalid_request_id_is_not_echoed(client_raw):
    invalid_request_id = "request id with spaces"

    response = client_raw.get(
        "/health",
        headers={"X-Request-ID": invalid_request_id},
    )

    assert response.status_code == 200
    assert response.headers.get("X-Request-ID") != invalid_request_id
    assert len(response.headers["X-Request-ID"]) == 32


def test_request_validation_does_not_echo_sensitive_input(client_raw):
    sensitive_password = "s3cr"

    response = client_raw.post(
        "/api/v1/auth/login",
        json={
            "company_id": str(uuid.uuid4()),
            "email": "admin@example.com",
            "password": sensitive_password,
            "device_id": "test-device",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert sensitive_password not in response.text
    assert all(
        set(error) == {"type", "loc", "msg"}
        for error in response.json()["error"]["meta"]
    )


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


def test_request_log_redacts_public_token_and_query_values(client_raw, caplog):
    public_token = "public-bearer-token-that-must-not-be-logged"
    audience = "private-audience-that-must-not-be-logged"

    with caplog.at_level(logging.INFO, logger=main_module.__name__):
        response = client_raw.get(
            f"/api/v1/public/files/{public_token}",
            params={"aud": audience},
        )

    assert response.status_code == 404
    records = [
        json.loads(record.message)
        for record in caplog.records
        if '"event": "http.request.completed"' in record.message
    ]
    assert records
    assert records[-1]["path"] == "/api/v1/public/files/{token}"
    assert records[-1]["query_keys"] == ["aud"]
    app_log_text = "\n".join(
        record.message
        for record in caplog.records
        if record.name == main_module.__name__
    )
    assert public_token not in app_log_text
    assert audience not in app_log_text


def test_failed_request_log_omits_internal_error_message(caplog):
    app = main_module.create_app()

    @app.get("/_test/observability-failure/{item_id}")
    def fail(item_id: str):
        raise RuntimeError(f"sensitive-internal-detail-{item_id}")

    with TestClient(app) as client:
        with caplog.at_level(logging.ERROR):
            response = client.get("/_test/observability-failure/private-item")

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "INTERNAL_ERROR",
            "message": "Internal server error",
            "field": None,
            "meta": None,
        }
    }
    assert response.headers.get("X-Request-ID")
    records = [
        json.loads(record.message)
        for record in caplog.records
        if '"event": "http.request.failed"' in record.message
    ]
    assert records
    assert records[-1]["path"] == "/_test/observability-failure/{item_id}"
    assert records[-1]["error_type"] == "RuntimeError"
    app_log_text = "\n".join(
        record.message
        for record in caplog.records
        if record.name == main_module.__name__
    )
    assert "sensitive-internal-detail" not in app_log_text
    assert "private-item" not in app_log_text
