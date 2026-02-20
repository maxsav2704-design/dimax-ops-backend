from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security.jwt import decode_and_validate_access
from app.shared.domain.errors import Forbidden
from app.shared.infrastructure.db.uow_sqlalchemy import SqlAlchemyUnitOfWork

bearer = HTTPBearer(auto_error=True)


@dataclass(frozen=True)
class CurrentUser:
    id: uuid.UUID
    company_id: uuid.UUID
    role: str  # "ADMIN" | "INSTALLER"


def get_uow() -> SqlAlchemyUnitOfWork:
    return SqlAlchemyUnitOfWork()


def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(bearer),
) -> CurrentUser:
    token = creds.credentials
    payload = decode_and_validate_access(token)

    try:
        return CurrentUser(
            id=uuid.UUID(payload["sub"]),
            company_id=uuid.UUID(payload["company_id"]),
            role=str(payload["role"]),
        )
    except Exception:
        raise Forbidden("Invalid token claims")


def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if user.role != "ADMIN":
        raise Forbidden("Admin only")
    return user


def require_installer(
    user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    if user.role not in ("INSTALLER", "ADMIN"):
        raise Forbidden("Installer only")
    return user
