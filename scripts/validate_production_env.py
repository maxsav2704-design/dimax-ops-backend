from __future__ import annotations

import argparse
import os
import re
import sys
from collections.abc import Mapping
from email.utils import parseaddr
from pathlib import Path
from urllib.parse import parse_qs, urlparse


TRUE_VALUES = {"1", "true", "yes"}
FALSE_VALUES = {"0", "false", "no"}
POSTGRES_SCHEMES = {"postgresql", "postgresql+psycopg", "postgresql+psycopg2"}
POSTGRES_SSL_MODES = {"require", "verify-ca", "verify-full"}
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "db", "postgres", "minio"}
PLACEHOLDER_MARKERS = (
    "example.com",
    "replace",
    "placeholder",
    "changeme",
    "change-me",
    "todo",
)
EXPLICIT_BOOLEAN_KEYS = (
    "EMAIL_ENABLED",
    "WHATSAPP_ENABLED",
    "WHATSAPP_FALLBACK_TO_EMAIL",
    "TWILIO_WEBHOOK_VALIDATE",
    "MINIO_SECURE",
)
RUNTIME_REQUIRED_KEYS = (
    "DATABASE_URL",
    "JWT_SECRET",
    "PUBLIC_BASE_URL",
    "PUBLIC_APP_BASE_URL",
    "CORS_ALLOW_ORIGINS",
    "MINIO_ENDPOINT",
    "MINIO_ACCESS_KEY",
    "MINIO_SECRET_KEY",
    "MINIO_BUCKET",
    *EXPLICIT_BOOLEAN_KEYS,
)
RELEASE_METADATA_KEYS = (
    "DIMAX_BACKEND_IMAGE",
    "SEED_ADMIN_EMAIL",
    "SEED_ADMIN_PASSWORD",
)
REQUIRED_KEYS = (*RELEASE_METADATA_KEYS, *RUNTIME_REQUIRED_KEYS)
SHA_TAG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*[0-9a-f]{12,64}$")
DIGEST_IMAGE_PATTERN = re.compile(r"^[^\s@]+@sha256:[0-9a-f]{64}$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate backend production environment values."
    )
    parser.add_argument(
        "--env-file",
        help="Optional env file to validate instead of the current process environment.",
    )
    parser.add_argument(
        "--runtime",
        action="store_true",
        help=(
            "Validate only values required by an already-built production container. "
            "Release image identity and one-shot bootstrap credentials remain part of "
            "the full pre-deploy validation."
        ),
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
        value = value.strip().strip('"').strip("'")
        result[key] = value
    return result


def value_of(env: Mapping[str, str], key: str) -> str:
    return str(env.get(key, "")).strip()


def has_placeholder_value(value: str) -> bool:
    text = value.lower()
    return any(marker in text for marker in PLACEHOLDER_MARKERS)


def parse_boolean(name: str, env: Mapping[str, str], errors: list[str]) -> bool:
    value = value_of(env, name).lower()
    if value in TRUE_VALUES:
        return True
    if value in FALSE_VALUES:
        return False
    errors.append(f"{name} must be an explicit true/false value")
    return False


def validate_url(
    name: str,
    value: str,
    *,
    require_https: bool,
    origin_only: bool = False,
) -> list[str]:
    if not value:
        return [f"{name} is required"]

    errors: list[str] = []
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc or not parsed.hostname:
        return [f"{name} must be a full URL"]
    if require_https and parsed.scheme.lower() != "https":
        errors.append(f"{name} must use https in production")
    if parsed.hostname.lower() in LOCAL_HOSTS:
        errors.append(f"{name} must not point to a local service in production")
    if parsed.username or parsed.password:
        errors.append(f"{name} must not contain URL credentials")
    if parsed.query or parsed.fragment:
        errors.append(f"{name} must not contain a query string or fragment")
    if origin_only and parsed.path not in {"", "/"}:
        errors.append(f"{name} must be an origin without a path")
    if has_placeholder_value(value):
        errors.append(f"{name} must not use placeholder/example production value")
    return errors


def validate_database_url(value: str) -> list[str]:
    if not value:
        return ["DATABASE_URL is required"]

    errors: list[str] = []
    parsed = urlparse(value)
    if parsed.scheme.lower() not in POSTGRES_SCHEMES:
        errors.append("DATABASE_URL must use a supported PostgreSQL scheme")
    if not parsed.hostname:
        errors.append("DATABASE_URL must include a database host")
    elif parsed.hostname.lower() in LOCAL_HOSTS:
        errors.append("DATABASE_URL must not use a local Docker host in production")
    if not parsed.username:
        errors.append("DATABASE_URL must include a database user")
    if parsed.password is None or parsed.password == "":
        errors.append("DATABASE_URL must include a database password")
    if not parsed.path.strip("/"):
        errors.append("DATABASE_URL must include a database name")
    ssl_mode = parse_qs(parsed.query).get("sslmode", [""])[-1].lower()
    if ssl_mode not in POSTGRES_SSL_MODES:
        errors.append(
            "DATABASE_URL must require TLS with sslmode=require, verify-ca, or verify-full"
        )
    if has_placeholder_value(value):
        errors.append("DATABASE_URL must not use placeholder/example production value")
    return errors


def validate_backend_image(value: str) -> list[str]:
    if not value:
        return ["DIMAX_BACKEND_IMAGE is required"]
    if has_placeholder_value(value):
        return ["DIMAX_BACKEND_IMAGE must not use a placeholder/example registry"]
    if DIGEST_IMAGE_PATTERN.fullmatch(value):
        return []

    name, separator, tag = value.rpartition(":")
    if not separator or not name or not SHA_TAG_PATTERN.fullmatch(tag):
        return [
            "DIMAX_BACKEND_IMAGE must use a sha256 digest or a release tag "
            "ending with a 12-64 character source SHA"
        ]
    return []


def validate_email(name: str, value: str) -> list[str]:
    if not value:
        return [f"{name} is required"]
    _display_name, address = parseaddr(value)
    if address != value or "@" not in address:
        return [f"{name} must be a plain email address"]
    local_part, domain = address.rsplit("@", 1)
    if not local_part or "." not in domain or domain.endswith(".local"):
        return [f"{name} must use a real production email domain"]
    if has_placeholder_value(value):
        return [f"{name} must not use placeholder/example production value"]
    return []


def validate_cors_origins(value: str) -> list[str]:
    if not value:
        return ["CORS_ALLOW_ORIGINS is required"]
    origins = [item.strip() for item in value.split(",") if item.strip()]
    if not origins:
        return ["CORS_ALLOW_ORIGINS must contain at least one HTTPS origin"]

    errors: list[str] = []
    for index, origin in enumerate(origins, start=1):
        name = f"CORS_ALLOW_ORIGINS entry {index}"
        if origin == "*":
            errors.append("CORS_ALLOW_ORIGINS must not contain a wildcard")
            continue
        errors.extend(validate_url(name, origin, require_https=True, origin_only=True))
    return errors


def validate_minio(env: Mapping[str, str]) -> list[str]:
    errors: list[str] = []
    endpoint = value_of(env, "MINIO_ENDPOINT")
    if not endpoint:
        errors.append("MINIO_ENDPOINT is required")
    elif "://" in endpoint:
        errors.append("MINIO_ENDPOINT must be host[:port] without a URL scheme")
    else:
        parsed = urlparse(f"//{endpoint}")
        if not parsed.hostname:
            errors.append("MINIO_ENDPOINT must include a storage host")
        elif parsed.hostname.lower() in LOCAL_HOSTS:
            errors.append("MINIO_ENDPOINT must not use a local service in production")
        if parsed.path not in {"", "/"}:
            errors.append("MINIO_ENDPOINT must not include a path")
        if has_placeholder_value(endpoint):
            errors.append("MINIO_ENDPOINT must not use a placeholder/example value")

    access_key = value_of(env, "MINIO_ACCESS_KEY")
    secret_key = value_of(env, "MINIO_SECRET_KEY")
    bucket = value_of(env, "MINIO_BUCKET")
    if len(access_key) < 3 or has_placeholder_value(access_key):
        errors.append("MINIO_ACCESS_KEY must be a real production access key")
    if len(secret_key) < 16 or has_placeholder_value(secret_key):
        errors.append("MINIO_SECRET_KEY must be at least 16 characters and non-placeholder")
    if (
        not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket)
        or ".." in bucket
    ):
        errors.append("MINIO_BUCKET must be a valid S3 bucket name")
    return errors


def validate_smtp(env: Mapping[str, str]) -> list[str]:
    errors: list[str] = []
    host = value_of(env, "SMTP_HOST")
    user = value_of(env, "SMTP_USER")
    password = value_of(env, "SMTP_PASSWORD")
    if not host or host.lower() in LOCAL_HOSTS or has_placeholder_value(host):
        errors.append("SMTP_HOST must be a real mail host when EMAIL_ENABLED=true")
    try:
        port = int(value_of(env, "SMTP_PORT"))
    except ValueError:
        port = 0
    if not 1 <= port <= 65535:
        errors.append("SMTP_PORT must be a valid TCP port when EMAIL_ENABLED=true")
    if value_of(env, "SMTP_TLS").lower() not in TRUE_VALUES:
        errors.append("SMTP_TLS must be true when EMAIL_ENABLED=true")
    if not user or has_placeholder_value(user):
        errors.append("SMTP_USER must be configured when EMAIL_ENABLED=true")
    if len(password) < 12 or has_placeholder_value(password):
        errors.append("SMTP_PASSWORD must be at least 12 characters and non-placeholder")
    errors.extend(validate_email("SMTP_FROM", value_of(env, "SMTP_FROM")))
    return errors


def validate_whatsapp(
    env: Mapping[str, str],
    *,
    email_enabled: bool,
    whatsapp_enabled: bool,
    fallback_to_email: bool,
    webhook_validation_enabled: bool,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    account_sid = value_of(env, "TWILIO_ACCOUNT_SID")
    auth_token = value_of(env, "TWILIO_AUTH_TOKEN")
    whatsapp_from = value_of(env, "TWILIO_WHATSAPP_FROM")
    credentials = (account_sid, auth_token, whatsapp_from)
    has_any_credentials = any(credentials)
    has_all_credentials = all(credentials)

    if has_any_credentials and not has_all_credentials:
        errors.append("Twilio WhatsApp credentials must be configured as a complete set")

    if whatsapp_enabled and has_all_credentials:
        if not account_sid.startswith("AC") or len(account_sid) < 12:
            errors.append("TWILIO_ACCOUNT_SID must be a real Twilio account SID")
        if len(auth_token) < 16 or has_placeholder_value(auth_token):
            errors.append("TWILIO_AUTH_TOKEN must be at least 16 characters and non-placeholder")
        if not re.fullmatch(r"whatsapp:\+[1-9][0-9]{7,14}", whatsapp_from):
            errors.append("TWILIO_WHATSAPP_FROM must use whatsapp:+<E.164 number>")
        callback_url = value_of(env, "TWILIO_STATUS_CALLBACK_URL")
        errors.extend(
            validate_url(
                "TWILIO_STATUS_CALLBACK_URL",
                callback_url,
                require_https=True,
            )
        )
        if not webhook_validation_enabled:
            errors.append(
                "TWILIO_WEBHOOK_VALIDATE must be true when Twilio WhatsApp delivery is enabled"
            )
    elif whatsapp_enabled:
        if not fallback_to_email:
            errors.append(
                "WHATSAPP_ENABLED requires complete Twilio credentials or "
                "WHATSAPP_FALLBACK_TO_EMAIL=true"
            )
        elif not email_enabled:
            errors.append(
                "WHATSAPP_FALLBACK_TO_EMAIL requires EMAIL_ENABLED=true "
                "when Twilio credentials are absent"
            )
        else:
            warnings.append(
                "WhatsApp delivery has no Twilio credentials and will rely on email fallback"
            )

    return errors, warnings


def _validate_environment(
    env: Mapping[str, str],
    *,
    include_release_metadata: bool,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    required_keys = REQUIRED_KEYS if include_release_metadata else RUNTIME_REQUIRED_KEYS
    for key in required_keys:
        if not value_of(env, key):
            errors.append(f"{key} is required")

    boolean_values = {
        key: parse_boolean(key, env, errors) for key in EXPLICIT_BOOLEAN_KEYS
    }

    jwt_secret = value_of(env, "JWT_SECRET")
    if len(jwt_secret) < 32 or has_placeholder_value(jwt_secret):
        errors.append("JWT_SECRET must be at least 32 characters and non-placeholder")

    if include_release_metadata:
        admin_password = value_of(env, "SEED_ADMIN_PASSWORD")
        if len(admin_password) < 14 or has_placeholder_value(admin_password):
            errors.append(
                "SEED_ADMIN_PASSWORD must be at least 14 characters and non-placeholder"
            )
        errors.extend(
            validate_email("SEED_ADMIN_EMAIL", value_of(env, "SEED_ADMIN_EMAIL"))
        )
        errors.extend(validate_backend_image(value_of(env, "DIMAX_BACKEND_IMAGE")))
    errors.extend(validate_database_url(value_of(env, "DATABASE_URL")))
    errors.extend(
        validate_url(
            "PUBLIC_BASE_URL",
            value_of(env, "PUBLIC_BASE_URL"),
            require_https=True,
        )
    )
    errors.extend(
        validate_url(
            "PUBLIC_APP_BASE_URL",
            value_of(env, "PUBLIC_APP_BASE_URL"),
            require_https=True,
        )
    )
    errors.extend(validate_cors_origins(value_of(env, "CORS_ALLOW_ORIGINS")))
    errors.extend(validate_minio(env))

    if not boolean_values["MINIO_SECURE"]:
        errors.append("MINIO_SECURE must be true in production")

    outbox_token = value_of(env, "OUTBOX_WEBHOOK_TOKEN")
    if outbox_token and (len(outbox_token) < 32 or has_placeholder_value(outbox_token)):
        errors.append(
            "OUTBOX_WEBHOOK_TOKEN must be at least 32 characters and non-placeholder when enabled"
        )

    email_enabled = boolean_values["EMAIL_ENABLED"]
    if not email_enabled:
        errors.append(
            "EMAIL_ENABLED must be true in production for signed journal PDF delivery"
        )
    else:
        errors.extend(validate_smtp(env))

    whatsapp_errors, whatsapp_warnings = validate_whatsapp(
        env,
        email_enabled=email_enabled,
        whatsapp_enabled=boolean_values["WHATSAPP_ENABLED"],
        fallback_to_email=boolean_values["WHATSAPP_FALLBACK_TO_EMAIL"],
        webhook_validation_enabled=boolean_values["TWILIO_WEBHOOK_VALIDATE"],
    )
    errors.extend(whatsapp_errors)
    warnings.extend(whatsapp_warnings)

    for name in ("SYNC_ALERT_WEBHOOK_URL", "PLAN_ALERT_WEBHOOK_URL"):
        value = value_of(env, name)
        if value:
            errors.extend(validate_url(name, value, require_https=True))

    return errors, warnings


def validate_environment(env: Mapping[str, str]) -> tuple[list[str], list[str]]:
    return _validate_environment(env, include_release_metadata=True)


def validate_runtime_environment(
    env: Mapping[str, str],
) -> tuple[list[str], list[str]]:
    return _validate_environment(env, include_release_metadata=False)


def main() -> int:
    args = parse_args()

    if args.env_file:
        try:
            env: Mapping[str, str] = load_env_file(Path(args.env_file))
        except FileNotFoundError as exc:
            print(str(exc), file=sys.stderr)
            return 2
    else:
        env = dict(os.environ)

    validator = validate_runtime_environment if args.runtime else validate_environment
    errors, warnings = validator(env)
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
