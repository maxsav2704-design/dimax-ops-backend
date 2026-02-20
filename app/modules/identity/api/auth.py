from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.v1.deps import CurrentUser, get_current_user, get_uow
from app.core.security.jwt import (
    create_access_token,
    create_refresh_token,
    decode_and_validate_refresh,
)
from app.core.security.password import verify_password
from app.modules.identity.api.schemas import LoginBody, RefreshBody, TokenPair
from app.modules.identity.infrastructure.refresh_tokens_models import RefreshTokenORM
from app.shared.domain.errors import Forbidden, NotFound

router = APIRouter(prefix="/auth", tags=["Auth"])


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid(val: str) -> UUID:
    return UUID(val)


@router.post("/login", response_model=TokenPair)
def login(body: LoginBody, uow=Depends(get_uow)):
    with uow:
        user = uow.users.get_by_email(
            company_id=body.company_id, email=str(body.email).lower()
        )
        if not user:
            raise NotFound("User not found")

        if not verify_password(body.password, user.password_hash):
            raise Forbidden("Invalid credentials")

        access, access_payload = create_access_token(
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
                    refresh_payload["exp"], tz=timezone.utc
                ),
            )
        )

    return TokenPair(access_token=access, refresh_token=refresh)


@router.post("/refresh", response_model=TokenPair)
def refresh_tokens(body: RefreshBody, uow=Depends(get_uow)):
    payload = decode_and_validate_refresh(body.refresh_token)

    company_id = payload["company_id"]
    user_id = payload["sub"]
    old_jti = payload["jti"]

    with uow:
        db_token = uow.refresh_tokens.get_active_by_jti(
            company_id=_uuid(company_id), jti=old_jti
        )
        if not db_token:
            raise Forbidden("Refresh token revoked or not found")

        if db_token.token_hash != _hash_token(body.refresh_token):
            raise Forbidden("Refresh token mismatch")

        # rotation: выдаём новую пару, старый refresh — revoke
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
            db_token, revoked_at=utcnow(), replaced_by_jti=new_payload["jti"]
        )
        uow.refresh_tokens.add(
            RefreshTokenORM(
                company_id=_uuid(company_id),
                user_id=_uuid(user_id),
                jti=new_payload["jti"],
                token_hash=_hash_token(new_refresh),
                expires_at=datetime.fromtimestamp(
                    new_payload["exp"], tz=timezone.utc
                ),
            )
        )

    return TokenPair(access_token=access, refresh_token=new_refresh)


@router.post("/logout")
def logout(
    current: CurrentUser = Depends(get_current_user),
    uow=Depends(get_uow),
):
    """
    Мини-logout: чтобы корректно сделать logout именно refresh'ем, обычно
    фронт вызывает /logout с refresh token — но пока упростим.
    Дальше сделаем /logout(refresh_token) и revoke конкретного jti.
    """
    return {"ok": True}
