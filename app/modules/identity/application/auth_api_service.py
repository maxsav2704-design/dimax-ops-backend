from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import text

from app.core.security.jwt import (
    create_access_token,
    create_refresh_token,
    decode_and_validate_refresh,
)
from app.core.security.password import verify_password
from app.core.security.refresh_token_hash import (
    hash_refresh_token,
    verify_refresh_token_hash,
)
from app.modules.identity.api.schemas import TokenPair
from app.modules.identity.infrastructure.refresh_tokens_models import RefreshTokenORM
from app.shared.domain.errors import (
    Forbidden,
    InvalidCredentials,
    NotFound,
    RefreshTokenReuse,
    Unauthorized,
)
from app.shared.infrastructure.observability import get_logger, log_event


logger = get_logger(__name__)


def _hash_token(token: str) -> str:
    return hash_refresh_token(token)


def _verify_token_hash(raw_token: str, stored_hash: str) -> bool:
    return verify_refresh_token_hash(raw_token, stored_hash)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid(val: str) -> UUID:
    return UUID(val)


def _company_is_active(uow, company_id: UUID) -> bool:
    value = uow.session.execute(
        text("SELECT is_active FROM companies WHERE id = :company_id"),
        {"company_id": company_id},
    ).scalar_one_or_none()
    return bool(value)


class AuthApiService:
    @staticmethod
    def _profile_payload(
        uow,
        *,
        company_id: UUID,
        user_id: UUID,
        full_name: str,
        role,
    ) -> dict:
        installer_row = (
            uow.session.execute(
                text(
                    """
                    SELECT display_name, language
                    FROM installer_profiles
                    WHERE company_id = :company_id AND user_id = :user_id
                    LIMIT 1
                    """
                ),
                {"company_id": company_id, "user_id": user_id},
            )
            .mappings()
            .first()
        )

        display_name = (
            str((installer_row or {}).get("display_name") or "").strip() if installer_row else ""
        ) or full_name
        language = (
            str((installer_row or {}).get("language") or "").strip().lower() if installer_row else ""
        ) or "en"
        if language not in {"ru", "en", "he"}:
            language = "en"

        payload = {
            "display_name": display_name,
            "language": language,
            "admin_scope": None,
            "can_view_rates": None,
            "can_manage_imports": None,
            "can_manage_users": None,
        }
        role_value = role.value if hasattr(role, "value") else str(role)
        if role_value != "ADMIN":
            return payload

        admin_row = (
            uow.session.execute(
                text(
                    """
                    SELECT admin_scope, can_view_rates, can_manage_imports, can_manage_users
                    FROM admin_profiles
                    WHERE company_id = :company_id AND user_id = :user_id
                    LIMIT 1
                    """
                ),
                {"company_id": company_id, "user_id": user_id},
            )
            .mappings()
            .first()
        )
        if not admin_row:
            payload.update(
                {
                    "can_view_rates": False,
                    "can_manage_imports": False,
                    "can_manage_users": False,
                }
            )
            return payload

        payload.update(
            {
                "admin_scope": str(admin_row.get("admin_scope") or "").strip() or None,
                "can_view_rates": bool(admin_row.get("can_view_rates")),
                "can_manage_imports": bool(admin_row.get("can_manage_imports")),
                "can_manage_users": bool(admin_row.get("can_manage_users")),
            }
        )
        return payload

    @staticmethod
    def get_me(
        uow,
        *,
        company_id: UUID,
        user_id: UUID,
    ) -> dict:
        user = uow.users.get_by_id(company_id=company_id, user_id=user_id)
        if not user:
            raise NotFound("User not found")
        profile = AuthApiService._profile_payload(
            uow,
            company_id=user.company_id,
            user_id=user.id,
            full_name=user.full_name,
            role=user.role,
        )
        return {
            "id": user.id,
            "company_id": user.company_id,
            "email": user.email,
            "full_name": user.full_name,
            "display_name": profile["display_name"],
            "language": profile["language"],
            "role": user.role,
            "is_active": user.is_active,
            "admin_scope": profile["admin_scope"],
            "can_view_rates": profile["can_view_rates"],
            "can_manage_imports": profile["can_manage_imports"],
            "can_manage_users": profile["can_manage_users"],
        }

    @staticmethod
    def login(
        uow,
        *,
        company_id: UUID,
        email: str,
        password: str,
        device_id: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> TokenPair:
        normalized_email = email.lower()
        log_event(
            logger,
            "auth.login.attempt",
            company_id=company_id,
            email=normalized_email,
        )
        user = uow.users.get_by_email(
            company_id=company_id,
            email=normalized_email,
        )
        company_active = _company_is_active(uow, company_id)
        if not company_active or not user:
            log_event(
                logger,
                "auth.login.failed",
                level="warning",
                company_id=company_id,
                email=normalized_email,
                reason=(
                    "user_inactive_or_missing"
                    if company_active
                    else "company_inactive_or_missing"
                ),
            )
            raise InvalidCredentials("Invalid credentials")

        if not verify_password(password, user.password_hash):
            log_event(
                logger,
                "auth.login.failed",
                level="warning",
                company_id=company_id,
                user_id=user.id,
                email=normalized_email,
                reason="invalid_credentials",
            )
            raise InvalidCredentials("Invalid credentials")

        profile = AuthApiService._profile_payload(
            uow,
            company_id=user.company_id,
            user_id=user.id,
            full_name=user.full_name,
            role=user.role,
        )

        access, _ = create_access_token(
            user_id=user.id,
            company_id=user.company_id,
            role=user.role.value,
        )
        refresh, refresh_payload = create_refresh_token(
            user_id=user.id,
            company_id=user.company_id,
            role=user.role.value,
        )

        uow.refresh_tokens.add(
            RefreshTokenORM(
                company_id=user.company_id,
                user_id=user.id,
                jti=refresh_payload["jti"],
                token_hash=_hash_token(refresh),
                device_id=device_id,
                issued_at=utcnow(),
                last_used_at=utcnow(),
                ip_address=ip_address,
                user_agent=user_agent,
                expires_at=datetime.fromtimestamp(
                    refresh_payload["exp"],
                    tz=timezone.utc,
                ),
            )
        )

        log_event(
            logger,
            "auth.login.succeeded",
            company_id=user.company_id,
            user_id=user.id,
            email=user.email,
            role=user.role,
        )

        return TokenPair(
            access_token=access,
            refresh_token=refresh,
            user={
                "id": user.id,
                "role": user.role,
                "language": profile["language"],
                "display_name": profile["display_name"],
                "admin_scope": profile["admin_scope"],
                "can_view_rates": profile["can_view_rates"],
                "can_manage_imports": profile["can_manage_imports"],
                "can_manage_users": profile["can_manage_users"],
            },
        )

    @staticmethod
    def refresh_tokens(
        uow,
        *,
        refresh_token: str,
        device_id: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> TokenPair:
        payload = decode_and_validate_refresh(refresh_token)

        company_id = payload["company_id"]
        user_id = payload["sub"]
        old_jti = payload["jti"]

        db_token = uow.refresh_tokens.get_by_jti(
            company_id=_uuid(company_id),
            jti=old_jti,
        )
        if not db_token:
            log_event(
                logger,
                "auth.refresh.failed",
                level="warning",
                company_id=company_id,
                user_id=user_id,
                reason="refresh_not_found",
            )
            raise Forbidden("Refresh token revoked or not found")

        if db_token.revoked_at is not None:
            log_event(
                logger,
                "auth.refresh.failed",
                level="warning",
                company_id=company_id,
                user_id=user_id,
                reason="refresh_reuse",
            )
            uow.refresh_tokens.revoke_all_active_by_user(
                company_id=_uuid(company_id),
                user_id=_uuid(user_id),
                revoked_at=utcnow(),
                revoke_reason="REPLAY_DETECTED",
            )
            raise RefreshTokenReuse("Refresh token reuse detected")

        if not _verify_token_hash(refresh_token, db_token.token_hash):
            log_event(
                logger,
                "auth.refresh.failed",
                level="warning",
                company_id=company_id,
                user_id=user_id,
                reason="refresh_mismatch",
            )
            uow.refresh_tokens.revoke_all_active_by_user(
                company_id=_uuid(company_id),
                user_id=_uuid(user_id),
                revoked_at=utcnow(),
                revoke_reason="REPLAY_DETECTED",
            )
            raise RefreshTokenReuse("Refresh token reuse detected")

        user = uow.users.get_by_id(
            company_id=_uuid(company_id),
            user_id=_uuid(user_id),
        )
        if user is None or not _company_is_active(uow, _uuid(company_id)):
            log_event(
                logger,
                "auth.refresh.failed",
                level="warning",
                company_id=company_id,
                user_id=user_id,
                reason="user_inactive_or_missing",
            )
            raise Unauthorized("Refresh session user is inactive or no longer exists")

        current_role = user.role.value if hasattr(user.role, "value") else str(user.role)
        now = utcnow()
        db_token.last_used_at = now
        if ip_address:
            db_token.ip_address = ip_address
        if user_agent:
            db_token.user_agent = user_agent

        access, _ = create_access_token(
            user_id=_uuid(user_id),
            company_id=_uuid(company_id),
            role=current_role,
        )
        new_refresh, new_payload = create_refresh_token(
            user_id=_uuid(user_id),
            company_id=_uuid(company_id),
            role=current_role,
        )

        uow.refresh_tokens.revoke(
            db_token,
            revoked_at=now,
            revoke_reason="ROTATION",
            replaced_by_jti=new_payload["jti"],
        )
        uow.refresh_tokens.add(
            RefreshTokenORM(
                company_id=_uuid(company_id),
                user_id=_uuid(user_id),
                jti=new_payload["jti"],
                token_hash=_hash_token(new_refresh),
                device_id=device_id or db_token.device_id,
                issued_at=now,
                last_used_at=now,
                ip_address=ip_address or db_token.ip_address,
                user_agent=user_agent or db_token.user_agent,
                expires_at=datetime.fromtimestamp(
                    new_payload["exp"],
                    tz=timezone.utc,
                ),
            )
        )

        log_event(
            logger,
            "auth.refresh.succeeded",
            company_id=company_id,
            user_id=user_id,
        )


        profile = AuthApiService._profile_payload(
            uow,
            company_id=_uuid(company_id),
            user_id=_uuid(user_id),
            full_name=user.full_name,
            role=current_role,
        )
        return TokenPair(
            access_token=access,
            refresh_token=new_refresh,
            user={
                "id": _uuid(user_id),
                "role": current_role,
                "language": profile["language"],
                "display_name": profile["display_name"],
                "admin_scope": profile["admin_scope"],
                "can_view_rates": profile["can_view_rates"],
                "can_manage_imports": profile["can_manage_imports"],
                "can_manage_users": profile["can_manage_users"],
            },
        )

    @staticmethod
    def logout(
        uow,
        *,
        company_id: UUID,
        user_id: UUID,
    ) -> dict:
        revoked_count = uow.refresh_tokens.revoke_all_active_by_user(
            company_id=company_id,
            user_id=user_id,
            revoked_at=utcnow(),
            revoke_reason="LOGOUT",
        )
        return {"ok": True, "user_id": user_id, "revoked_count": revoked_count}

    @staticmethod
    def logout_refresh(
        uow,
        *,
        refresh_token: str,
    ) -> dict:
        payload = decode_and_validate_refresh(refresh_token)
        company_id = _uuid(payload["company_id"])
        old_jti = payload["jti"]

        db_token = uow.refresh_tokens.get_active_by_jti(
            company_id=company_id,
            jti=old_jti,
        )
        if not db_token:
            log_event(
                logger,
                "auth.logout_refresh.missed",
                company_id=company_id,
                reason="refresh_not_found",
            )
            return {"ok": True, "revoked": False}

        if not _verify_token_hash(refresh_token, db_token.token_hash):
            log_event(
                logger,
                "auth.logout_refresh.failed",
                level="warning",
                company_id=company_id,
                user_id=db_token.user_id,
                reason="refresh_mismatch",
            )
            raise Forbidden("Refresh token mismatch")

        uow.refresh_tokens.revoke(
            db_token,
            revoked_at=utcnow(),
            revoke_reason="LOGOUT",
        )
        log_event(
            logger,
            "auth.logout_refresh.succeeded",
            company_id=company_id,
            user_id=db_token.user_id,
        )
        return {"ok": True, "revoked": True}

    @staticmethod
    def logout_all(
        uow,
        *,
        company_id: UUID,
        user_id: UUID,
    ) -> dict:
        revoked_count = uow.refresh_tokens.revoke_all_active_by_user(
            company_id=company_id,
            user_id=user_id,
            revoked_at=utcnow(),
            revoke_reason="LOGOUT",
        )
        log_event(
            logger,
            "auth.logout_all.succeeded",
            company_id=company_id,
            user_id=user_id,
            revoked_count=revoked_count,
        )
        return {"ok": True, "revoked_count": revoked_count}
