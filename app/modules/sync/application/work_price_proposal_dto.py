from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StringConstraints, field_validator

from app.modules.rates.application.timeline_dto import FactoryWorkPriceContext
from app.modules.sync.application.price_review_dto import ExecutionTimeCorrection, PriceConflictSource

Evidence = Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=500)]
Digest = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]


class ReviewWorkPriceProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    execution_correction: ExecutionTimeCorrection | None = None


class CreateWorkPriceProposal(ReviewWorkPriceProposal):
    request_id: UUID
    review_token: Digest
    rate: Decimal = Field(gt=0, max_digits=12, decimal_places=2, allow_inf_nan=False)
    reason: Evidence
    agreement_reference: Evidence
    execution_evidence: Evidence
    confirm_execution_evidence: StrictBool

    @field_validator("confirm_execution_evidence")
    @classmethod
    def require_evidence(cls, value):
        if not value:
            raise ValueError("Execution, quantity and assignment evidence must be checked")
        return value


class WorkPriceScope(BaseModel):
    source: PriceConflictSource
    item_id: UUID
    project_id: UUID
    project_name: str
    installer_id: UUID
    installer_name: str
    work_label: str
    quantity: Decimal
    unit: str
    missing_price: FactoryWorkPriceContext
    execution_correction: ExecutionTimeCorrection | None


class WorkPriceProposal(BaseModel):
    id: UUID
    version: int
    status: Literal["PREPARED"] = "PREPARED"
    scope: WorkPriceScope
    rate: Decimal
    amount: Decimal
    currency: Literal["ILS"] = "ILS"
    reason: str
    agreement_reference: str
    execution_evidence: str
    snapshot_hash: str
    created_by: UUID
    created_at: datetime
    affects_earnings: Literal[False] = False
    invitation_sent: Literal[False] = False


class WorkPriceProposalReview(BaseModel):
    review_token: str
    scope: WorkPriceScope
    latest: WorkPriceProposal | None
