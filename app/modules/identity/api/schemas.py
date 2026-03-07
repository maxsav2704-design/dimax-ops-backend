from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.modules.identity.domain.enums import UserRole


class LoginBody(BaseModel):
    company_id: UUID
    email: EmailStr
    password: str = Field(min_length=6, max_length=200)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshBody(BaseModel):
    refresh_token: str


class LogoutRefreshBody(BaseModel):
    refresh_token: str


class LogoutResponse(BaseModel):
    ok: bool
    user_id: UUID


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
    role: UserRole
    is_active: bool
