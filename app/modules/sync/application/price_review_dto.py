from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

from app.modules.rates.application.timeline_dto import FactoryPriceQuote

PriceConflictSource = Literal["sync_event", "sync_queue"]


class ExecutionTimeCorrection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    performed_at: AwareDatetime
    evidence_reference: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=500)]


class PriceConflictReview(BaseModel):
    source: PriceConflictSource
    id: UUID
    project_id: UUID | None
    project_name: str | None = None
    installer_id: UUID | None
    installer_name: str | None = None
    work_kind: Literal["DOOR", "ADDON"] | None = None
    work_label: str | None = None
    performed_at: datetime | None
    received_at: datetime
    quantity: str | None = None
    seen_price_list_id: str | None = None
    seen_version: int | None = None
    seen_version_status: Literal["MISSING", "INVALID", "UNAVAILABLE", "AVAILABLE"] = "MISSING"
    analysis_code: Literal[
        "VERSION_MISMATCH", "VERSION_MATCH", "NO_VERSION", "INVALID_VERSION",
        "MISSING_EXECUTION_TIME", "INVALID_EXECUTION_TIME", "NO_ACTIVE_FACTORY_PRICES",
        "MISSING_FACTORY_PRICE", "INVALID_FACTORY_EVIDENCE", "WORK_UNAVAILABLE",
        "INVALID_QUANTITY", "UNSUPPORTED_WORK", "CATALOG_UNIT_CHANGED",
        "ORIGINAL_PRICE_UNAVAILABLE",
        "ASSIGNMENT_EVIDENCE_REQUIRED", "HISTORICAL_PRICE_REVIEW", "LEGACY_EXECUTION_REVIEW",
        "EXECUTION_TIME_CORRECTION",
    ]
    applicable_quote: FactoryPriceQuote | None = None
    preview_amount: Decimal | None = None
    work_context: Literal["CURRENT_CATALOG"] = "CURRENT_CATALOG"
    resolution_available: bool = False
    requires_execution_evidence: bool = False
    time_correction_available: bool = False
    execution_correction: ExecutionTimeCorrection | None = None
    review_token: str | None = None


class ResolvePriceConflict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    review_token: str = Field(pattern=r"^[a-f0-9]{64}$")
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=500)]
    confirm_execution_evidence: bool = False
    execution_correction: ExecutionTimeCorrection | None = None


class PriceConflictResolution(BaseModel):
    id: UUID
    completed_work_id: UUID
    price_list_id: UUID
    amount: Decimal
    resolved_at: datetime
    reason: str
