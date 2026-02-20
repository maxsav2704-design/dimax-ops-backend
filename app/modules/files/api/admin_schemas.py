from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class FileDownloadEventDTO(BaseModel):
    created_at: datetime
    source: str
    correlation_id: UUID | None
    ip: str | None
    user_agent: str | None
    actor_user_id: UUID | None
    file_name: str | None


class FileDownloadEventsResponse(BaseModel):
    items: list[FileDownloadEventDTO]
