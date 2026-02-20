from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class InstallerCreateDTO(BaseModel):
    full_name: str = Field(min_length=2, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=40)
    email: Optional[str] = Field(default=None, max_length=255)
    address: Optional[str] = Field(default=None, max_length=500)
    passport_id: Optional[str] = Field(default=None, max_length=80)
    notes: Optional[str] = Field(default=None, max_length=1000)
    status: str = Field(default="ACTIVE", max_length=20)
    is_active: bool = True
    user_id: Optional[uuid.UUID] = None


class InstallerUpdateDTO(BaseModel):
    """user_id is not updatable via PATCH; use link-user / unlink-user endpoints."""

    full_name: Optional[str] = Field(default=None, min_length=2, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=40)
    email: Optional[str] = Field(default=None, max_length=255)
    address: Optional[str] = Field(default=None, max_length=500)
    passport_id: Optional[str] = Field(default=None, max_length=80)
    notes: Optional[str] = Field(default=None, max_length=1000)
    status: Optional[str] = Field(default=None, max_length=20)
    is_active: Optional[bool] = None


class InstallerDTO(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    full_name: str
    phone: Optional[str]
    email: Optional[str]
    status: str
    is_active: bool
    user_id: Optional[uuid.UUID]
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime]

    model_config = {"from_attributes": True}


class LinkUserDTO(BaseModel):
    user_id: uuid.UUID
