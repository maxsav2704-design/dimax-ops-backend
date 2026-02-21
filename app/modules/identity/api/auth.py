from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.v1.deps import CurrentUser, get_current_user, get_uow
from app.api.v1.rate_limit import rate_limit_auth_login, rate_limit_auth_refresh
from app.modules.identity.application.auth_api_service import AuthApiService
from app.modules.identity.api.schemas import (
    LoginBody,
    LogoutAllResponse,
    LogoutRefreshResponse,
    LogoutResponse,
    LogoutRefreshBody,
    RefreshBody,
    TokenPair,
)

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/login", response_model=TokenPair)
def login(
    body: LoginBody,
    _rl=Depends(rate_limit_auth_login),
    uow=Depends(get_uow),
):
    with uow:
        return AuthApiService.login(
            uow,
            company_id=body.company_id,
            email=str(body.email),
            password=body.password,
        )


@router.post("/refresh", response_model=TokenPair)
def refresh_tokens(
    body: RefreshBody,
    _rl=Depends(rate_limit_auth_refresh),
    uow=Depends(get_uow),
):
    with uow:
        return AuthApiService.refresh_tokens(
            uow,
            refresh_token=body.refresh_token,
        )


@router.post("/logout", response_model=LogoutResponse)
def logout(current: CurrentUser = Depends(get_current_user)) -> LogoutResponse:
    return {"ok": True, "user_id": str(current.id)}


@router.post("/logout-refresh", response_model=LogoutRefreshResponse)
def logout_refresh(
    body: LogoutRefreshBody,
    uow=Depends(get_uow),
) -> LogoutRefreshResponse:
    with uow:
        return AuthApiService.logout_refresh(
            uow,
            refresh_token=body.refresh_token,
        )


@router.post("/logout-all", response_model=LogoutAllResponse)
def logout_all(
    current: CurrentUser = Depends(get_current_user),
    uow=Depends(get_uow),
) -> LogoutAllResponse:
    with uow:
        return AuthApiService.logout_all(
            uow,
            company_id=current.company_id,
            user_id=current.id,
        )
