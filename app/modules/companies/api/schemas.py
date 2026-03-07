from __future__ import annotations

import uuid
from datetime import datetime

from decimal import Decimal

from pydantic import BaseModel, EmailStr, Field

from app.modules.identity.domain.enums import UserRole

class PlatformCompanyCreateDTO(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    admin_email: EmailStr
    admin_password: str = Field(min_length=6, max_length=200)
    admin_full_name: str = Field(min_length=2, max_length=255)


class PlatformCompanyStatusUpdateDTO(BaseModel):
    is_active: bool


class PlatformCompanyDTO(BaseModel):
    id: uuid.UUID
    name: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PlatformCompanyCreateResponseDTO(BaseModel):
    company: PlatformCompanyDTO
    admin_user_id: uuid.UUID


class PlatformCompanyListResponseDTO(BaseModel):
    items: list[PlatformCompanyDTO]
    total: int
    limit: int
    offset: int


class PlatformCompanyPlanDTO(BaseModel):
    company_id: uuid.UUID
    plan_code: str
    is_active: bool
    max_users: int | None
    max_admin_users: int | None
    max_installer_users: int | None
    max_installers: int | None
    max_projects: int | None
    max_doors_per_project: int | None
    monthly_price: Decimal | None
    currency: str
    notes: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PlatformCompanyPlanUpdateDTO(BaseModel):
    plan_code: str = Field(min_length=2, max_length=32)
    is_active: bool = True
    max_users: int | None = Field(default=None, ge=1, le=100000)
    max_admin_users: int | None = Field(default=None, ge=1, le=100000)
    max_installer_users: int | None = Field(default=None, ge=1, le=100000)
    max_installers: int | None = Field(default=None, ge=1, le=100000)
    max_projects: int | None = Field(default=None, ge=1, le=1000000)
    max_doors_per_project: int | None = Field(default=None, ge=1, le=1000000)
    monthly_price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    notes: str | None = Field(default=None, max_length=500)


class PlatformCompanyUsageDTO(BaseModel):
    active_users: int
    active_admin_users: int
    active_installer_users: int
    active_installers: int
    active_projects: int
    total_doors: int


class PlatformCompanyUserCreateDTO(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=255)
    password: str = Field(min_length=6, max_length=200)
    role: UserRole = UserRole.ADMIN
    is_active: bool = True


class PlatformCompanyUserDTO(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    email: EmailStr
    full_name: str
    role: UserRole
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
