from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class DoorTypeCreateDTO(BaseModel):
    code: str = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=2, max_length=256)
    is_active: bool = True


class DoorTypeUpdateDTO(BaseModel):
    code: str | None = Field(
        default=None, min_length=2, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"
    )
    name: str | None = Field(default=None, min_length=2, max_length=256)
    is_active: bool | None = None


class DoorTypeDTO(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    code: str
    name: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None

    model_config = {"from_attributes": True}


class DoorTypesExportResponse(BaseModel):
    items: list[DoorTypeDTO]


class DoorTypeImportItemDTO(BaseModel):
    code: str = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=2, max_length=256)
    is_active: bool = True


class DoorTypesImportBody(BaseModel):
    items: list[DoorTypeImportItemDTO] = Field(min_length=1, max_length=5000)
    create_only: bool = False


class DoorTypesImportResponse(BaseModel):
    created: int
    updated: int
    unchanged: int
    skipped_existing: int


class DoorTypesBulkBody(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=5000)
    operation: str = Field(pattern="^(activate|deactivate|delete)$")


class DoorTypesBulkResponse(BaseModel):
    affected: int
    not_found: int
    unchanged: int
