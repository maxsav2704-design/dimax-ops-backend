from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class InstallerDoorInstallBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MarkNotInstalledBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason_id: UUID
    comment: str | None = Field(default=None, max_length=1000)


class InstallerDoorStatusUpdateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(pattern="^(IN_PROGRESS|INSTALLED)$")


class InstallerDoorStatusUpdateResponse(BaseModel):
    id: UUID
    status: str
    version: int


class DoorActionResponse(BaseModel):
    ok: bool = True
    id: UUID
    status: str
    version: int


class AdminOverrideBody(BaseModel):
    new_status: str = Field(pattern="^(INSTALLED|NOT_INSTALLED)$")
    reason_id: UUID | None = None
    comment: str | None = Field(default=None, max_length=1000)
    override_reason: str | None = Field(default=None, max_length=500)


class OkResponse(BaseModel):
    ok: bool = True
