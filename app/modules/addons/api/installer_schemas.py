from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class AddFactBody(BaseModel):
    addon_type_id: UUID
    qty_done: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    done_at: datetime | None = None
    comment: str | None = None
    client_event_id: str | None = None


class AddFactResponse(BaseModel):
    ok: bool
    applied: bool
    fact_id: UUID | None


class InstallerProjectAddonsResponse(BaseModel):
    project_id: UUID
    plan: list[dict]
    facts: list[dict]
