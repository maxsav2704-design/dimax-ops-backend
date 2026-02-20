from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class MarkNotInstalledBody(BaseModel):
    reason_id: UUID
    comment: str | None = Field(default=None, max_length=1000)


class AdminOverrideBody(BaseModel):
    new_status: str = Field(pattern="^(INSTALLED|NOT_INSTALLED)$")
    reason_id: UUID | None = None
    comment: str | None = Field(default=None, max_length=1000)
    override_reason: str | None = Field(default=None, max_length=500)


class OkResponse(BaseModel):
    ok: bool = True
