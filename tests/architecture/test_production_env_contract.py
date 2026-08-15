from __future__ import annotations

import sys
from pathlib import Path

from scripts import validate_production_env


def _valid_env() -> dict[str, str]:
    return {
        "DIMAX_BACKEND_IMAGE": "registry.dimax.co.il/dimax/backend:git-0123456789ab",
        "DATABASE_URL": (
            "postgresql+psycopg2://dimax_app:S3cureDbPass@db.dimax.co.il:5432/"
            "dimax?sslmode=require"
        ),
        "JWT_SECRET": "a" * 64,
        "SEED_ADMIN_EMAIL": "owner@dimax.co.il",
        "SEED_ADMIN_PASSWORD": "StrongAdminPass!2026",
        "PUBLIC_BASE_URL": "https://api.dimax.co.il",
        "CORS_ALLOW_ORIGINS": "https://ops.dimax.co.il",
        "MINIO_ENDPOINT": "s3.dimax.co.il:443",
        "MINIO_ACCESS_KEY": "DIMAXACCESS",
        "MINIO_SECRET_KEY": "long-storage-secret-2026",
        "MINIO_BUCKET": "dimax-production",
        "MINIO_SECURE": "true",
        "EMAIL_ENABLED": "false",
        "WHATSAPP_ENABLED": "false",
        "WHATSAPP_FALLBACK_TO_EMAIL": "false",
        "TWILIO_WEBHOOK_VALIDATE": "false",
    }


def test_valid_production_environment_passes() -> None:
    errors, warnings = validate_production_env.validate_environment(_valid_env())

    assert errors == []
    assert warnings == []


def test_database_requires_tls() -> None:
    env = _valid_env()
    env["DATABASE_URL"] = env["DATABASE_URL"].replace("?sslmode=require", "")

    errors, _warnings = validate_production_env.validate_environment(env)

    assert any("DATABASE_URL must require TLS" in error for error in errors)


def test_backend_image_rejects_latest_and_floating_tags() -> None:
    for image in (
        "dimax-backend:latest",
        "registry.dimax.co.il/dimax/backend:v1.0.0",
        "dimax-backend",
    ):
        env = _valid_env()
        env["DIMAX_BACKEND_IMAGE"] = image

        errors, _warnings = validate_production_env.validate_environment(env)

        assert any("DIMAX_BACKEND_IMAGE must use a sha256 digest" in error for error in errors)


def test_backend_image_accepts_sha256_digest() -> None:
    env = _valid_env()
    env["DIMAX_BACKEND_IMAGE"] = (
        "registry.dimax.co.il/dimax/backend@sha256:" + ("a" * 64)
    )

    errors, warnings = validate_production_env.validate_environment(env)

    assert errors == []
    assert warnings == []


def test_runtime_environment_does_not_require_release_only_metadata() -> None:
    env = _valid_env()
    for key in ("DIMAX_BACKEND_IMAGE", "SEED_ADMIN_EMAIL", "SEED_ADMIN_PASSWORD"):
        env.pop(key)

    errors, warnings = validate_production_env.validate_runtime_environment(env)

    assert errors == []
    assert warnings == []


def test_runtime_environment_rejects_development_security_defaults() -> None:
    env = _valid_env()
    env["JWT_SECRET"] = "change-me"

    errors, _warnings = validate_production_env.validate_runtime_environment(env)

    assert any("JWT_SECRET must be at least 32 characters" in error for error in errors)


def test_cors_rejects_wildcard_and_non_https_origins() -> None:
    env = _valid_env()
    env["CORS_ALLOW_ORIGINS"] = "*,http://ops.dimax.co.il"

    errors, _warnings = validate_production_env.validate_environment(env)

    assert any("must not contain a wildcard" in error for error in errors)
    assert any("must use https" in error for error in errors)


def test_integration_toggles_must_be_explicit() -> None:
    env = _valid_env()
    env.pop("EMAIL_ENABLED")

    errors, _warnings = validate_production_env.validate_environment(env)

    assert "EMAIL_ENABLED is required" in errors
    assert "EMAIL_ENABLED must be an explicit true/false value" in errors


def test_whatsapp_fallback_requires_configured_email() -> None:
    env = _valid_env()
    env.update(
        {
            "WHATSAPP_ENABLED": "true",
            "WHATSAPP_FALLBACK_TO_EMAIL": "true",
        }
    )

    errors, _warnings = validate_production_env.validate_environment(env)

    assert any(
        "WHATSAPP_FALLBACK_TO_EMAIL requires EMAIL_ENABLED=true" in error
        for error in errors
    )


def test_twilio_delivery_requires_callback_signature_validation() -> None:
    env = _valid_env()
    env.update(
        {
            "WHATSAPP_ENABLED": "true",
            "TWILIO_ACCOUNT_SID": "AC123456789012345678901234567890",
            "TWILIO_AUTH_TOKEN": "strong-twilio-auth-token",
            "TWILIO_WHATSAPP_FROM": "whatsapp:+972501234567",
            "TWILIO_STATUS_CALLBACK_URL": (
                "https://api.dimax.co.il/api/v1/webhooks/twilio/status"
            ),
        }
    )

    errors, _warnings = validate_production_env.validate_environment(env)

    assert any("TWILIO_WEBHOOK_VALIDATE must be true" in error for error in errors)


def test_env_file_does_not_inherit_missing_value_from_process(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    env = _valid_env()
    env.pop("JWT_SECRET")
    env_file = tmp_path / ".env.production"
    env_file.write_text(
        "\n".join(f"{key}={value}" for key, value in env.items()),
        encoding="utf-8",
    )
    monkeypatch.setenv("JWT_SECRET", "ambient-secret-that-must-not-be-used")
    monkeypatch.setattr(
        sys,
        "argv",
        ["validate_production_env.py", "--env-file", str(env_file)],
    )

    assert validate_production_env.main() == 1
    assert "JWT_SECRET is required" in capsys.readouterr().err


def test_production_container_contract_runs_fail_closed_runtime_validation() -> None:
    backend_root = Path(__file__).resolve().parents[2]
    dockerfile = (backend_root / "Dockerfile").read_text(encoding="utf-8")
    entrypoint = (backend_root / "docker-entrypoint.sh").read_text(encoding="utf-8")
    compose = (backend_root / "docker-compose.production.yml").read_text(
        encoding="utf-8"
    )

    assert 'ENTRYPOINT ["/usr/local/bin/dimax-entrypoint"]' in dockerfile
    assert 'if [ "${APP_ENV:-development}" = "production" ]' in entrypoint
    assert "validate_production_env.py --runtime" in entrypoint
    assert "APP_ENV: production" in compose
