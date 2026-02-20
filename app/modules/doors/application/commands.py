from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class MarkDoorInstalled:
    company_id: uuid.UUID
    actor_user_id: uuid.UUID
    door_id: uuid.UUID


@dataclass(frozen=True)
class MarkDoorNotInstalled:
    company_id: uuid.UUID
    actor_user_id: uuid.UUID
    door_id: uuid.UUID
    reason_id: uuid.UUID
    comment: str | None = None


@dataclass(frozen=True)
class AdminOverrideDoor:
    company_id: uuid.UUID
    actor_user_id: uuid.UUID
    door_id: uuid.UUID
    new_status: str  # "INSTALLED" | "NOT_INSTALLED"
    reason_id: uuid.UUID | None = None
    comment: str | None = None
    override_reason: str | None = None
