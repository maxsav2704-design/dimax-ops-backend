from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class DocumentTemplateDTO(BaseModel):
    id: UUID
    code: str
    name: str
    description: str | None = None
    entity_scope: str
    source_filename: str
    mime_type: str
    size_bytes: int
    placeholders: list[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime


class DocumentTemplatesResponse(BaseModel):
    items: list[DocumentTemplateDTO]


class DocumentTemplateUpdateBody(BaseModel):
    is_active: bool | None = None


class ProjectDocumentContextResponse(BaseModel):
    project_id: UUID
    fields: dict[str, Any]


class RenderProjectDocumentBody(BaseModel):
    template_id: UUID
    overrides: dict[str, Any] = Field(default_factory=dict)


class DocumentGenerationDTO(BaseModel):
    id: UUID
    template_id: UUID
    project_id: UUID
    template_name: str | None = None
    project_name: str | None = None
    project_code: str | None = None
    file_name: str
    mime_type: str
    size_bytes: int
    status: str
    download_url: str
    created_at: datetime


class DocumentGenerationsResponse(BaseModel):
    items: list[DocumentGenerationDTO]
