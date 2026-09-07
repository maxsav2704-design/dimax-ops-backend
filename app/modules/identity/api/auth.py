from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.api.v1.deps import CurrentUser, get_current_user, get_uow
from app.api.v1.rate_limit import rate_limit_auth_login, rate_limit_auth_refresh
from app.modules.identity.application.auth_api_service import AuthApiService
from app.modules.identity.api.schemas import (
    AuthMeResponse,
    LoginBody,
    LogoutAllResponse,
    LogoutRefreshResponse,
    LogoutResponse,
    LogoutRefreshBody,
    RefreshBody,
    TokenPair,
)
from app.shared.domain.errors import RefreshTokenReuse

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.get("/me", response_model=AuthMeResponse)
def auth_me(
    current: CurrentUser = Depends(get_current_user),
    uow=Depends(get_uow),
):
    with uow:
        return AuthApiService.get_me(
            uow,
            company_id=current.company_id,
            user_id=current.id,
        )


@router.post("/login", response_model=TokenPair)
def login(
    body: LoginBody,
    request: Request,
    _rl=Depends(rate_limit_auth_login),
    uow=Depends(get_uow),
):
    with uow:
        return AuthApiService.login(
            uow,
            company_id=body.company_id,
            email=str(body.email),
            password=body.password,
            device_id=body.device_id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )


@router.post("/refresh", response_model=TokenPair)
def refresh_tokens(
    body: RefreshBody,
    request: Request,
    _rl=Depends(rate_limit_auth_refresh),
    uow=Depends(get_uow),
):
    with uow:
        try:
            return AuthApiService.refresh_tokens(
                uow,
                refresh_token=body.refresh_token,
                device_id=body.device_id,
                ip_address=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
            )
        except RefreshTokenReuse:
            uow.commit()
            raise


@router.post("/logout", response_model=LogoutResponse)
def logout(
    current: CurrentUser = Depends(get_current_user),
    uow=Depends(get_uow),
) -> LogoutResponse:
    with uow:
        return AuthApiService.logout(
            uow,
            company_id=current.company_id,
            user_id=current.id,
        )


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
