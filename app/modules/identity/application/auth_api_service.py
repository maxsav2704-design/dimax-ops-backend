from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import UUID

from app.core.security.jwt import (
    create_access_token,
    create_refresh_token,
    decode_and_validate_refresh,
)
from app.core.security.password import verify_password
from app.modules.identity.api.schemas import TokenPair
from app.modules.identity.infrastructure.refresh_tokens_models import RefreshTokenORM
from app.shared.domain.errors import Forbidden, NotFound
from app.shared.infrastructure.observability import get_logger, log_event


logger = get_logger(__name__)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid(val: str) -> UUID:
    return UUID(val)


class AuthApiService:
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
        return {
            "id": user.id,
            "company_id": user.company_id,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role,
            "is_active": user.is_active,
        }

    @staticmethod
    def login(
        uow,
        *,
        company_id: UUID,
        email: str,
        password: str,
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
        if not user:
            log_event(
                logger,
                "auth.login.failed",
                level="warning",
                company_id=company_id,
                email=normalized_email,
                reason="user_not_found",
            )
            raise NotFound("User not found")

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
            raise Forbidden("Invalid credentials")

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

        return TokenPair(access_token=access, refresh_token=refresh)

    @staticmethod
    def refresh_tokens(
        uow,
        *,
        refresh_token: str,
    ) -> TokenPair:
        payload = decode_and_validate_refresh(refresh_token)

        company_id = payload["company_id"]
        user_id = payload["sub"]
        old_jti = payload["jti"]

        db_token = uow.refresh_tokens.get_active_by_jti(
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

        if db_token.token_hash != _hash_token(refresh_token):
            log_event(
                logger,
                "auth.refresh.failed",
                level="warning",
                company_id=company_id,
                user_id=user_id,
                reason="refresh_mismatch",
            )
            raise Forbidden("Refresh token mismatch")

        access, _ = create_access_token(
            user_id=_uuid(user_id),
            company_id=_uuid(company_id),
            role=payload["role"],
        )
        new_refresh, new_payload = create_refresh_token(
            user_id=_uuid(user_id),
            company_id=_uuid(company_id),
            role=payload["role"],
        )

        uow.refresh_tokens.revoke(
            db_token,
            revoked_at=utcnow(),
            replaced_by_jti=new_payload["jti"],
        )
        uow.refresh_tokens.add(
            RefreshTokenORM(
                company_id=_uuid(company_id),
                user_id=_uuid(user_id),
                jti=new_payload["jti"],
                token_hash=_hash_token(new_refresh),
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

        return TokenPair(access_token=access, refresh_token=new_refresh)

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

        if db_token.token_hash != _hash_token(refresh_token):
            log_event(
                logger,
                "auth.logout_refresh.failed",
                level="warning",
                company_id=company_id,
                user_id=db_token.user_id,
                reason="refresh_mismatch",
            )
            raise Forbidden("Refresh token mismatch")

        uow.refresh_tokens.revoke(db_token, revoked_at=utcnow())
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
        )
        log_event(
            logger,
            "auth.logout_all.succeeded",
            company_id=company_id,
            user_id=user_id,
            revoked_count=revoked_count,
        )
        return {"ok": True, "revoked_count": revoked_count}
