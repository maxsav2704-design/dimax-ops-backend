from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from urllib.parse import urlparse


DEFAULT_DANGEROUS_VALUES = {
    "JWT_SECRET": {"", "change-me"},
    "SEED_ADMIN_PASSWORD": {"", "secret123"},
    "MINIO_ACCESS_KEY": {"", "minioadmin"},
    "MINIO_SECRET_KEY": {"", "minioadmin"},
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate backend production environment values."
    )
    parser.add_argument(
        "--env-file",
        help="Optional env file to load before validation.",
    )
    return parser.parse_args()


def load_env_file(file_path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if not file_path.exists():
        raise FileNotFoundError(f"Env file not found: {file_path}")
    for raw_line in file_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"").strip("'")
        result[key] = value
    return result


def merged_env(file_values: dict[str, str]) -> dict[str, str]:
    env = dict(os.environ)
    for key, value in file_values.items():
        if not str(env.get(key, "")).strip():
            env[key] = value
    return env


def is_local_host(value: str) -> bool:
    text = value.lower()
    return any(item in text for item in ("localhost", "127.0.0.1", "@db:", "minio:9000"))


def validate_url(name: str, value: str, *, require_https: bool) -> list[str]:
    errors: list[str] = []
    if not value:
        return [f"{name} is required"]
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        return [f"{name} must be a full URL"]
    if require_https and parsed.scheme != "https":
        errors.append(f"{name} must use https in production")
    if parsed.hostname in {"localhost", "127.0.0.1"}:
        errors.append(f"{name} must not point to localhost in production")
    return errors


def validate_database_url(value: str) -> list[str]:
    errors: list[str] = []
    if not value:
        return ["DATABASE_URL is required"]
    if "postgres:postgres@db:5432/dimax" in value or is_local_host(value):
        errors.append("DATABASE_URL must not use local/dev defaults in production")
    if "postgresql" not in value and "postgres" not in value:
        errors.append("DATABASE_URL must be a PostgreSQL URL")
    return errors


def main() -> int:
    args = parse_args()

    file_env: dict[str, str] = {}
    if args.env_file:
        try:
            file_env = load_env_file(Path(args.env_file))
        except FileNotFoundError as exc:
            print(str(exc), file=sys.stderr)
            return 2

    env = merged_env(file_env)
    errors: list[str] = []
    warnings: list[str] = []

    required_keys = [
        "DATABASE_URL",
        "JWT_SECRET",
        "PUBLIC_BASE_URL",
        "CORS_ALLOW_ORIGINS",
        "MINIO_ENDPOINT",
        "MINIO_ACCESS_KEY",
        "MINIO_SECRET_KEY",
        "MINIO_BUCKET",
    ]
    for key in required_keys:
        if not str(env.get(key, "")).strip():
            errors.append(f"{key} is required")

    for key, dangerous_values in DEFAULT_DANGEROUS_VALUES.items():
        if str(env.get(key, "")).strip() in dangerous_values:
            errors.append(f"{key} still uses a default or empty production value")

    jwt_secret = str(env.get("JWT_SECRET", ""))
    if jwt_secret and len(jwt_secret) < 24:
        errors.append("JWT_SECRET must be at least 24 characters")

    errors.extend(validate_database_url(str(env.get("DATABASE_URL", ""))))
    errors.extend(validate_url("PUBLIC_BASE_URL", str(env.get("PUBLIC_BASE_URL", "")), require_https=True))

    cors_origins = str(env.get("CORS_ALLOW_ORIGINS", ""))
    if not cors_origins:
        errors.append("CORS_ALLOW_ORIGINS is required")
    elif any(item in cors_origins.lower() for item in ("localhost", "127.0.0.1")):
        errors.append("CORS_ALLOW_ORIGINS must not include localhost entries in production")

    minio_endpoint = str(env.get("MINIO_ENDPOINT", ""))
    if is_local_host(minio_endpoint):
        errors.append("MINIO_ENDPOINT must not use local/dev defaults in production")
    if str(env.get("MINIO_SECURE", "")).strip().lower() not in {"true", "1", "yes"}:
        errors.append("MINIO_SECURE must be true in production")

    email_enabled = str(env.get("EMAIL_ENABLED", "")).strip().lower() in {"true", "1", "yes"}
    smtp_host = str(env.get("SMTP_HOST", "")).strip()
    if email_enabled:
        if not smtp_host or smtp_host.lower() == "localhost":
            errors.append("SMTP_HOST must be set to a real mail host when EMAIL_ENABLED=true")
        smtp_from = str(env.get("SMTP_FROM", "")).strip().lower()
        if smtp_from.endswith(".local"):
            errors.append("SMTP_FROM must not use a .local address in production")

    whatsapp_enabled = str(env.get("WHATSAPP_ENABLED", "")).strip().lower() in {"true", "1", "yes"}
    fallback_to_email = str(env.get("WHATSAPP_FALLBACK_TO_EMAIL", "")).strip().lower() in {"true", "1", "yes"}
    twilio_account_sid = str(env.get("TWILIO_ACCOUNT_SID", "")).strip()
    twilio_auth_token = str(env.get("TWILIO_AUTH_TOKEN", "")).strip()
    twilio_from = str(env.get("TWILIO_WHATSAPP_FROM", "")).strip()
    if whatsapp_enabled and not (twilio_account_sid and twilio_auth_token and twilio_from):
        if not fallback_to_email:
            errors.append(
                "WHATSAPP_ENABLED requires Twilio credentials or WHATSAPP_FALLBACK_TO_EMAIL=true"
            )
        else:
            warnings.append(
                "WHATSAPP_ENABLED is true but Twilio credentials are missing; delivery relies on email fallback"
            )

    if errors:
        print("Production env validation failed:", file=sys.stderr)
        for item in errors:
            print(f"- {item}", file=sys.stderr)
        if warnings:
            print("Warnings:", file=sys.stderr)
            for item in warnings:
                print(f"- {item}", file=sys.stderr)
        return 1

    print("Backend production env is valid.")
    if warnings:
        print("Warnings:")
        for item in warnings:
            print(f"- {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
