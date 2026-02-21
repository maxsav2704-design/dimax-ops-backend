from __future__ import annotations

from pydantic import BaseModel, Field


class SharePdfBody(BaseModel):
    ttl_sec: int = Field(default=3600, ge=60, le=7 * 24 * 3600)
    uses: int = Field(default=3, ge=1, le=20)
    audience: str | None = Field(default=None, max_length=120)


class SharePdfResponse(BaseModel):
    url: str
    ttl_sec: int
    uses: int
