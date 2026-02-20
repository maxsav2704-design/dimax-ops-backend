from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import jwt

from app.core.config import settings
from app.shared.domain.errors import Forbidden

ALGO = "HS256"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _encode(payload: dict) -> str:
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=ALGO)


def _decode(token: str) -> dict:
    try:
        return jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[ALGO],
            options={"require": ["exp", "iat", "iss", "sub"]},
            issuer=settings.JWT_ISSUER,
        )
    except jwt.ExpiredSignatureError:
        raise Forbidden("Token expired")
    except jwt.InvalidTokenError:
        raise Forbidden("Invalid token")


def create_access_token(
    *, user_id: uuid.UUID, company_id: uuid.UUID, role: str
) -> tuple[str, dict]:
    now = utcnow()
    exp = now + timedelta(minutes=settings.JWT_ACCESS_TTL_MIN)
    jti = uuid.uuid4()

    payload = {
        "iss": settings.JWT_ISSUER,
        "sub": str(user_id),
        "company_id": str(company_id),
        "role": role,
        "type": "access",
        "jti": str(jti),
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    return _encode(payload), payload


def create_refresh_token(
    *, user_id: uuid.UUID, company_id: uuid.UUID, role: str
) -> tuple[str, dict]:
    now = utcnow()
    exp = now + timedelta(days=settings.JWT_REFRESH_TTL_DAYS)
    jti = uuid.uuid4()

    payload = {
        "iss": settings.JWT_ISSUER,
        "sub": str(user_id),
        "company_id": str(company_id),
        "role": role,
        "type": "refresh",
        "jti": str(jti),
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    return _encode(payload), payload


def decode_and_validate_access(token: str) -> dict:
    payload = _decode(token)
    if payload.get("type") != "access":
        raise Forbidden("Expected access token")
    return payload


def decode_and_validate_refresh(token: str) -> dict:
    payload = _decode(token)
    if payload.get("type") != "refresh":
        raise Forbidden("Expected refresh token")
    return payload
