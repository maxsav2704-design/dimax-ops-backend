from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

EVENT_TYPE_PATTERN = "^(installation|delivery|meeting|consultation|inspection)$"


class EventCreateBody(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    event_type: str = Field(pattern=EVENT_TYPE_PATTERN)
    starts_at: datetime
    ends_at: datetime
    location: str | None = Field(default=None, max_length=400)
    description: str | None = Field(default=None, max_length=5000)
    project_id: UUID | None = None
    installer_ids: list[UUID] = Field(default_factory=list, max_length=50)


class EventUpdateBody(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    event_type: str | None = Field(default=None, pattern=EVENT_TYPE_PATTERN)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    location: str | None = Field(default=None, max_length=400)
    description: str | None = Field(default=None, max_length=5000)
    project_id: UUID | None = None
    installer_ids: list[UUID] | None = None


class EventDTO(BaseModel):
    id: UUID
    title: str
    event_type: str
    starts_at: datetime
    ends_at: datetime
    location: str | None
    waze_url: str | None
    description: str | None
    project_id: UUID | None
    installer_ids: list[UUID]


class EventListResponse(BaseModel):
    items: list[EventDTO]


class EventCreateResponse(BaseModel):
    id: UUID


class OkResponse(BaseModel):
    ok: bool = True
