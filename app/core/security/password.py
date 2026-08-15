from __future__ import annotations

import re

import bcrypt


BCRYPT_MAX_PASSWORD_BYTES = 72
BCRYPT_ROUNDS = 12
_BCRYPT_HASH_RE = re.compile(
    r"^\$2[aby]\$(?:0[4-9]|[12][0-9]|3[01])\$[./A-Za-z0-9]{53}$"
)


def password_size_bytes(raw: str) -> int:
    return len(raw.encode("utf-8"))


def validate_new_password(raw: str) -> str:
    if password_size_bytes(raw) > BCRYPT_MAX_PASSWORD_BYTES:
        raise ValueError(
            f"Password must not exceed {BCRYPT_MAX_PASSWORD_BYTES} UTF-8 bytes"
        )
    return raw


def hash_password(raw: str) -> str:
    validate_new_password(raw)
    return bcrypt.hashpw(
        raw.encode("utf-8"),
        bcrypt.gensalt(rounds=BCRYPT_ROUNDS),
    ).decode("ascii")


def verify_password(raw: str, hashed: str) -> bool:
    if not isinstance(raw, str) or not isinstance(hashed, str):
        return False
    if _BCRYPT_HASH_RE.fullmatch(hashed) is None:
        return False

    try:
        # Existing bcrypt hashes use the historical 72-byte truncation rule.
        candidate = raw.encode("utf-8")[:BCRYPT_MAX_PASSWORD_BYTES]
        return bcrypt.checkpw(candidate, hashed.encode("ascii"))
    except (TypeError, ValueError, UnicodeError):
        return False
