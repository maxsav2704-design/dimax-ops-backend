from __future__ import annotations

from hmac import compare_digest
import uuid
from dataclasses import dataclass

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text

from app.core.config import settings
from app.core.security.jwt import decode_and_validate_access
from app.shared.domain.errors import Forbidden, ForbiddenScope
from app.shared.infrastructure.db.uow_sqlalchemy import SqlAlchemyUnitOfWork

bearer = HTTPBearer(auto_error=True)
_SAFE_ADMIN_METHODS = {"GET", "HEAD", "OPTIONS"}
_ADMIN_READ_PREFIXES: dict[str, tuple[str, ...]] = {
    "OPERATIONS": (
        "/api/v1/admin/addons",
        "/api/v1/admin/calendar",
        "/api/v1/admin/dashboard",
        "/api/v1/admin/documents",
        "/api/v1/admin/door-types",
        "/api/v1/admin/doors",
        "/api/v1/admin/earnings",
        "/api/v1/admin/files",
        "/api/v1/admin/installer-rates",
        "/api/v1/admin/installers",
        "/api/v1/admin/issues",
        "/api/v1/admin/journals",
        "/api/v1/admin/library",
        "/api/v1/admin/outbox",
        "/api/v1/admin/projects",
        "/api/v1/admin/reasons",
        "/api/v1/admin/reports",
        "/api/v1/admin/sync",
    ),
    "FINANCE": (
        "/api/v1/admin/door-types",
        "/api/v1/admin/earnings",
        "/api/v1/admin/installer-rates",
        "/api/v1/admin/installers",
        "/api/v1/admin/outbox",
        "/api/v1/admin/projects",
        "/api/v1/admin/reports",
    ),
    "VIEWER": (
        "/api/v1/admin/addons",
        "/api/v1/admin/calendar",
        "/api/v1/admin/dashboard",
        "/api/v1/admin/documents",
        "/api/v1/admin/door-types",
        "/api/v1/admin/doors",
        "/api/v1/admin/files",
        "/api/v1/admin/installers",
        "/api/v1/admin/issues",
        "/api/v1/admin/journals",
        "/api/v1/admin/library",
        "/api/v1/admin/projects",
        "/api/v1/admin/reasons",
    ),
}


def _path_matches_prefix(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(f"{prefix}/")


def _admin_scope_can_read_path(scope: str, path: str) -> bool:
    if scope == "OWNER":
        return True
    return any(
        _path_matches_prefix(path, prefix)
        for prefix in _ADMIN_READ_PREFIXES.get(scope, ())
    )


@dataclass(frozen=True)
class CurrentUser:
    id: uuid.UUID
    company_id: uuid.UUID
    role: str  # "ADMIN" | "INSTALLER"
    admin_scope: str | None = None
    can_view_rates: bool = False
    can_manage_imports: bool = False
    can_manage_users: bool = False


def get_uow() -> SqlAlchemyUnitOfWork:
    return SqlAlchemyUnitOfWork()


def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(bearer),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
) -> CurrentUser:
    payload = decode_and_validate_access(creds.credentials)

    try:
        user_id = uuid.UUID(payload["sub"])
        company_id = uuid.UUID(payload["company_id"])
        token_role = str(payload["role"])
    except Exception as exc:
        raise Forbidden("Invalid token claims") from exc

    with uow:
        assert uow.session is not None
        row = (
            uow.session.execute(
                text(
                    """
                    SELECT
                        users.role,
                        users.is_active,
                        companies.is_active AS company_is_active,
                        admin_profiles.admin_scope,
                        admin_profiles.can_view_rates,
                        admin_profiles.can_manage_imports,
                        admin_profiles.can_manage_users
                    FROM users
                    JOIN companies
                      ON companies.id = users.company_id
                    LEFT JOIN admin_profiles
                      ON admin_profiles.company_id = users.company_id
                     AND admin_profiles.user_id = users.id
                    WHERE users.company_id = :company_id
                      AND users.id = :user_id
                    LIMIT 1
                    """
                ),
                {"company_id": company_id, "user_id": user_id},
            )
            .mappings()
            .first()
        )

    if (
        not row
        or not bool(row.get("is_active"))
        or not bool(row.get("company_is_active"))
    ):
        raise Forbidden("User is inactive or unavailable")

    current_role = str(row.get("role") or "")
    if current_role not in {"ADMIN", "INSTALLER"} or current_role != token_role:
        raise Forbidden("User role changed; sign in again")

    return CurrentUser(
        id=user_id,
        company_id=company_id,
        role=current_role,
        admin_scope=(
            str(row.get("admin_scope") or "").strip() or None
            if current_role == "ADMIN"
            else None
        ),
        can_view_rates=(
            bool(row.get("can_view_rates")) if current_role == "ADMIN" else False
        ),
        can_manage_imports=(
            bool(row.get("can_manage_imports"))
            if current_role == "ADMIN"
            else False
        ),
        can_manage_users=(
            bool(row.get("can_manage_users")) if current_role == "ADMIN" else False
        ),
    )


def require_admin(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    if user.role != "ADMIN":
        raise ForbiddenScope("Admin role required")
    if user.admin_scope not in {"OWNER", "OPERATIONS", "FINANCE", "VIEWER"}:
        raise ForbiddenScope("Admin profile required")

    method = request.method.upper()
    if method not in _SAFE_ADMIN_METHODS:
        if user.admin_scope not in {"OWNER", "OPERATIONS"}:
            raise ForbiddenScope("Admin write scope required")
    elif not _admin_scope_can_read_path(user.admin_scope, request.url.path):
        raise ForbiddenScope("Admin read scope required")
    return user


def require_installer(
    user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    if user.role != "INSTALLER":
        raise ForbiddenScope("Installer role required")
    return user


def _admin_capabilities(
    uow: SqlAlchemyUnitOfWork,
    *,
    company_id: uuid.UUID,
    user_id: uuid.UUID,
) -> tuple[str | None, bool, bool, bool]:
    assert uow.session is not None
    row = uow.session.execute(
        text(
            """
            SELECT admin_scope, can_view_rates, can_manage_imports, can_manage_users
            FROM admin_profiles
            WHERE company_id = :company_id AND user_id = :user_id
            LIMIT 1
            """
        ),
        {"company_id": company_id, "user_id": user_id},
    ).mappings().first()
    if not row:
        return (None, False, False, False)
    return (
        str(row.get("admin_scope") or "").strip() or None,
        bool(row.get("can_view_rates")),
        bool(row.get("can_manage_imports")),
        bool(row.get("can_manage_users")),
    )


def ensure_admin_can_view_rates(
    uow: SqlAlchemyUnitOfWork, user: CurrentUser
) -> CurrentUser:
    if user.role != "ADMIN":
        raise ForbiddenScope("Admin role required")
    _scope, can_view_rates, _can_manage_imports, _can_manage_users = _admin_capabilities(
        uow, company_id=user.company_id, user_id=user.id
    )
    if not can_view_rates:
        raise ForbiddenScope("Admin rates access required")
    return user


def ensure_admin_can_manage_imports(
    uow: SqlAlchemyUnitOfWork, user: CurrentUser
) -> CurrentUser:
    if user.role != "ADMIN":
        raise ForbiddenScope("Admin role required")
    _scope, _can_view_rates, can_manage_imports, _can_manage_users = _admin_capabilities(
        uow, company_id=user.company_id, user_id=user.id
    )
    if not can_manage_imports:
        raise ForbiddenScope("Admin import access required")
    return user


def ensure_admin_can_manage_users(
    uow: SqlAlchemyUnitOfWork, user: CurrentUser
) -> CurrentUser:
    if user.role != "ADMIN":
        raise ForbiddenScope("Admin role required")
    _scope, _can_view_rates, _can_manage_imports, can_manage_users = _admin_capabilities(
        uow, company_id=user.company_id, user_id=user.id
    )
    if not can_manage_users:
        raise ForbiddenScope("Admin user management access required")
    return user


def ensure_admin_can_run_operations(
    uow: SqlAlchemyUnitOfWork, user: CurrentUser
) -> CurrentUser:
    if user.role != "ADMIN":
        raise ForbiddenScope("Admin role required")
    scope, _can_view_rates, _can_manage_imports, _can_manage_users = _admin_capabilities(
        uow, company_id=user.company_id, user_id=user.id
    )
    if scope not in {"OWNER", "OPERATIONS"}:
        raise ForbiddenScope("Admin operations scope required")
    return user


def require_platform_token(
    x_platform_token: str | None = Header(default=None, alias="X-Platform-Token"),
) -> None:
    expected = settings.PLATFORM_API_TOKEN.strip()
    if not expected:
        raise Forbidden("Platform API is disabled")
    if not x_platform_token or not compare_digest(x_platform_token, expected):
        raise Forbidden("Invalid platform token")
