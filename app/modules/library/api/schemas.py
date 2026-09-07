from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ProductLibraryItemDTO(BaseModel):
    id: uuid.UUID
    sku: str
    name_ru: str
    name_he: str
    install_type: str
    manufacturer: str | None
    unit: str
    status: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ProductLibraryListResponse(BaseModel):
    items: list[ProductLibraryItemDTO]


class ProductLibraryCreateBody(BaseModel):
    sku: str = Field(min_length=1, max_length=80)
    name_ru: str = Field(min_length=1, max_length=200)
    name_he: str = Field(min_length=1, max_length=200)
    install_type: str = Field(min_length=1, max_length=120)
    manufacturer: str | None = Field(default=None, max_length=200)
    unit: str = Field(default="piece", pattern=r"^(piece|set|point)$")
    status: str = Field(default="ACTIVE", pattern=r"^(ACTIVE|ARCHIVED)$")


class ProductLibraryUpdateBody(BaseModel):
    sku: str | None = Field(default=None, min_length=1, max_length=80)
    name_ru: str | None = Field(default=None, min_length=1, max_length=200)
    name_he: str | None = Field(default=None, min_length=1, max_length=200)
    install_type: str | None = Field(default=None, min_length=1, max_length=120)
    manufacturer: str | None = Field(default=None, max_length=200)
    unit: str | None = Field(default=None, pattern=r"^(piece|set|point)$")
    status: str | None = Field(default=None, pattern=r"^(ACTIVE|ARCHIVED)$")
