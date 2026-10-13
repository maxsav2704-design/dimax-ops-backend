from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StrictBool, field_validator

from app.modules.sync.application.work_price_proposal_dto import Digest, Evidence, WorkPriceScope


class AccrueWorkPrice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    approval_hash: Digest
    reason: Evidence
    confirm_accrual: StrictBool

    @field_validator("confirm_accrual")
    @classmethod
    def require_consent(cls, value):
        if not value:
            raise ValueError("Explicit accrual confirmation is required")
        return value


class WorkPriceAccrual(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    approval_id: UUID
    completed_work_id: UUID
    amount: Decimal
    accrued_at: datetime
    reason: str


class WorkPriceAccrualReview(BaseModel):
    approval_id: UUID
    approval_hash: str
    scope: WorkPriceScope
    reference: str
    rate: Decimal
    amount: Decimal
    currency: str = "ILS"
    confirmed_name: str
    confirmed_at: datetime
    accrual: WorkPriceAccrual | None = None
