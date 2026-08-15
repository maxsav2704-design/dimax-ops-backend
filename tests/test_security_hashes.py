from __future__ import annotations

import bcrypt
import pytest
from pydantic import ValidationError

from app.core.security.password import (
    BCRYPT_MAX_PASSWORD_BYTES,
    hash_password,
    validate_new_password,
    verify_password,
)
from app.core.security.refresh_token_hash import (
    hash_refresh_token,
    verify_refresh_token_hash,
)
from app.modules.companies.api.schemas import (
    PlatformCompanyCreateDTO,
    PlatformCompanyUserCreateDTO,
)


def test_password_hash_round_trip_and_wrong_password() -> None:
    hashed = hash_password("StrongPassword123!")

    assert hashed.startswith("$2b$12$")
    assert verify_password("StrongPassword123!", hashed) is True
    assert verify_password("WrongPassword123!", hashed) is False


def test_password_verification_accepts_existing_bcrypt_hash() -> None:
    existing_hash = "$2b$12$WVHKXbH3D3twVf1jqrnbDOZfO/EGAvWV/l60NvX6/2wAia7VKxV7m"

    assert verify_password("legacy-password", existing_hash) is True


def test_password_verification_rejects_malformed_or_unrelated_hashes() -> None:
    assert verify_password("password", "not-a-hash") is False
    assert verify_password("password", "$2b$12$invalid") is False


def test_new_password_rejects_more_than_72_utf8_bytes() -> None:
    valid = "a" * BCRYPT_MAX_PASSWORD_BYTES
    too_long = "я" * (BCRYPT_MAX_PASSWORD_BYTES // 2 + 1)

    assert validate_new_password(valid) == valid
    with pytest.raises(ValueError, match="72 UTF-8 bytes"):
        hash_password(too_long)


def test_existing_long_bcrypt_password_remains_verifiable() -> None:
    raw = "a" * (BCRYPT_MAX_PASSWORD_BYTES + 8)
    legacy_hash = bcrypt.hashpw(
        raw.encode("utf-8")[:BCRYPT_MAX_PASSWORD_BYTES],
        bcrypt.gensalt(rounds=12),
    ).decode("ascii")

    assert verify_password(raw, legacy_hash) is True


@pytest.mark.parametrize(
    "schema,payload,password_field",
    [
        (
            PlatformCompanyCreateDTO,
            {
                "name": "DIMAX Test",
                "admin_email": "owner@example.com",
                "admin_full_name": "DIMAX Owner",
            },
            "admin_password",
        ),
        (
            PlatformCompanyUserCreateDTO,
            {
                "email": "admin@example.com",
                "full_name": "DIMAX Admin",
            },
            "password",
        ),
    ],
)
def test_password_creation_dtos_reject_more_than_72_utf8_bytes(
    schema, payload: dict[str, str], password_field: str
) -> None:
    with pytest.raises(ValidationError, match="72 UTF-8 bytes"):
        schema(**payload, **{password_field: "я" * 37})


def test_refresh_token_hash_compares_the_complete_token() -> None:
    common_prefix = "x" * BCRYPT_MAX_PASSWORD_BYTES
    first = f"{common_prefix}:first-token-tail"
    second = f"{common_prefix}:second-token-tail"
    first_hash = hash_refresh_token(first)

    assert first_hash.startswith("sha256:")
    assert first_hash != hash_refresh_token(second)
    assert verify_refresh_token_hash(first, first_hash) is True
    assert verify_refresh_token_hash(second, first_hash) is False


def test_refresh_token_hash_accepts_existing_bcrypt_session() -> None:
    token = "legacy-refresh-token-" + "x" * 100
    legacy_hash = bcrypt.hashpw(
        token.encode("utf-8")[:BCRYPT_MAX_PASSWORD_BYTES],
        bcrypt.gensalt(rounds=12),
    ).decode("ascii")

    assert verify_refresh_token_hash(token, legacy_hash) is True
    assert verify_refresh_token_hash(token, "0" * 64) is False
