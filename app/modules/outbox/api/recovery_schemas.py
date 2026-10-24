from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RecoveryReason(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    reason: str = Field(min_length=1, max_length=1000)


class RecoveryDecisionBody(RecoveryReason):
    request_id: UUID
    expected_revision: int = Field(ge=0)
    action: Literal["HOLD", "RETRY", "ACCEPTED"]
    evidence: str = Field(min_length=1, max_length=1000)
    accepted_at: datetime | None = None

    @field_validator("accepted_at")
    @classmethod
    def timezone_required(cls, value):
        if value is not None and value.utcoffset() is None:
            raise ValueError("Timestamp must include a timezone")
        return value


class RecoveryItemDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    recovery_id: UUID
    outbox_id: UUID
    action: str | None
    revision: int


class RecoveryDecisionDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    item_id: UUID
    request_id: UUID
    revision: int
    action: str
    reason: str
    evidence: str
    accepted_at: datetime | None
    actor_id: UUID
    created_at: datetime


class RecoveryStatusDTO(BaseModel):
    epoch: UUID | None
    recovery_id: UUID | None
    state: Literal["NOT_ACTIVATED", "CONFIGURATION_REQUIRED", "REVIEW_REQUIRED", "REVIEW", "RELEASED"]
    unresolved: int = 0
    held: int = 0
