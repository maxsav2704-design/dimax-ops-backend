from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.modules.identity.domain.enums import UserRole


class LoginBody(BaseModel):
    company_id: UUID
    email: EmailStr
    password: str = Field(min_length=6, max_length=200)
    device_id: str = Field(min_length=1, max_length=255)


class AuthUserDTO(BaseModel):
    id: UUID
    role: UserRole
    language: str
    display_name: str
    admin_scope: str | None = None
    can_view_rates: bool | None = None
    can_manage_imports: bool | None = None
    can_manage_users: bool | None = None


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: AuthUserDTO


class RefreshBody(BaseModel):
    refresh_token: str
    device_id: str | None = Field(default=None, max_length=255)


class LogoutRefreshBody(BaseModel):
    refresh_token: str


class LogoutResponse(BaseModel):
    ok: bool
    user_id: UUID
    revoked_count: int


class LogoutRefreshResponse(BaseModel):
    ok: bool
    revoked: bool


class LogoutAllResponse(BaseModel):
    ok: bool
    revoked_count: int


class AuthMeResponse(BaseModel):
    id: UUID
    company_id: UUID
    email: EmailStr
    full_name: str
    display_name: str
    language: str
    role: UserRole
    is_active: bool
    admin_scope: str | None = None
    can_view_rates: bool | None = None
    can_manage_imports: bool | None = None
    can_manage_users: bool | None = None
