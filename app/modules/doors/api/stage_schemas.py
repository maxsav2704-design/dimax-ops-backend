from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

StageCode = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z][A-Za-z0-9_]{0,39}$")]
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


class StageDefinitionDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    code: str
    name: str
    sort_order: int
    is_active: bool


class CreateStageDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: StageCode
    name: Label
    sort_order: int = Field(default=0, ge=0, le=1000, strict=True)


class UpdateStageDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Label | None = None
    sort_order: int | None = Field(default=None, ge=0, le=1000, strict=True)
    is_active: bool | None = None


class StagePlanItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stage_code: StageCode
    required: bool = True


class CreateStagePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_latest_version: int = Field(ge=0, strict=True)
    reason: Reason
    items: list[StagePlanItemIn] = Field(min_length=1, max_length=40)


class StagePlanItemDTO(BaseModel):
    stage_code: str
    required: bool
    sequence: int


class StagePlanDTO(BaseModel):
    id: UUID
    door_type_id: UUID
    version: int
    reason: str
    created_by: UUID
    created_at: datetime
    items: list[StagePlanItemDTO]


class StagePlanPage(BaseModel):
    items: list[StagePlanDTO]
    latest_version: int


class ApplyDoorPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: UUID


class AssignStage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    installer_id: UUID


class CompleteStage(BaseModel):
    """Installer completion: no price, earning or approval field may ever appear here."""
    model_config = ConfigDict(extra="forbid")
    request_id: UUID | None = None
    happened_at: datetime | None = None


class AdminCompleteStage(CompleteStage):
    installer_id: UUID


class DoorStageDTO(BaseModel):
    stage_code: str
    name: str
    required: bool
    sequence: int
    installer_id: UUID | None
    assignment_id: UUID | None
    completed_at: datetime | None
    completed_by: UUID | None
    fact_id: UUID | None
    # Step 4: the earning that values the fact, or why there is none (never an amount here).
    earning_id: UUID | None = None
    earning_status: Literal["RECORDED", "NO_RATE", "PRICING_INACTIVE"] | None = None


class DoorStagesDTO(BaseModel):
    door_id: UUID
    door_status: str
    door_version: int
    plan_id: UUID
    plan_version: int
    stages: list[DoorStageDTO]
    required_total: int
    required_done: int
    installed_by_stages: bool


class StageCompletionResponse(BaseModel):
    id: UUID
    status: str
    version: int
    applied: bool
    required_total: int
    required_done: int
    door_installed: bool
    earning_status: Literal["RECORDED", "NO_RATE", "PRICING_INACTIVE"] | None = None
