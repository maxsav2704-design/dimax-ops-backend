from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class InstallerRateCreateDTO(BaseModel):
    installer_id: uuid.UUID
    door_type_id: uuid.UUID
    price: Decimal = Field(ge=0)
    effective_from: datetime | None = None

    @field_validator("effective_from")
    @classmethod
    def _effective_from_must_be_tz_aware(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return value
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError("effective_from must include timezone")
        return value


class InstallerRateUpdateDTO(BaseModel):
    price: Optional[Decimal] = Field(default=None, ge=0)
    effective_from: datetime | None = None

    @field_validator("effective_from")
    @classmethod
    def _effective_from_must_be_tz_aware(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return value
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError("effective_from must include timezone")
        return value


class InstallerRateDTO(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    installer_id: uuid.UUID
    door_type_id: uuid.UUID
    price: Decimal
    effective_from: datetime
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class InstallerRatesBulkBody(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=5000)
    operation: str = Field(pattern="^(set_price|delete)$")
    price: Optional[Decimal] = Field(default=None, ge=0)
    effective_from: datetime | None = None

    @field_validator("effective_from")
    @classmethod
    def _bulk_effective_from_must_be_tz_aware(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return value
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError("effective_from must include timezone")
        return value


class InstallerRatesBulkResponse(BaseModel):
    affected: int
    not_found: int
    unchanged: int


class InstallerRateTimelineResponse(BaseModel):
    installer_id: uuid.UUID
    door_type_id: uuid.UUID
    as_of: datetime
    effective_rate: InstallerRateDTO | None
    versions: list[InstallerRateDTO]
