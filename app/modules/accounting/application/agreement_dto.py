from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StrictBool, field_validator

from app.modules.accounting.application.dto import Reason


class ActivateCommercialAgreement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    approval_id: UUID
    effective_from: date
    reason: Reason
    accepted: StrictBool

    @field_validator("accepted")
    @classmethod
    def explicit_consent(cls, value):
        if not value:
            raise ValueError("Explicit OWNER consent to put these versions into effect is required")
        return value


AgreementStatus = Literal["SCHEDULED", "ACTIVE", "ENDED"]


class CommercialAgreementSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    contract_id: UUID
    terms_id: UUID
    price_id: UUID
    approval_id: UUID
    terms_version: int
    price_version: int
    billing_basis: str
    effective_from: date
    effective_until: date | None
    activated_by: UUID
    activated_by_name: str
    activated_at: datetime
    reason: str
    snapshot_hash: str
    status: AgreementStatus
    is_demo: bool
    usable_for_billing: Literal[False] = False


class CommercialAgreementPage(BaseModel):
    items: list[CommercialAgreementSummary]
    total: int
    activation_enabled: bool
    cutover: date
    today: date
    current: CommercialAgreementSummary | None


LineReason = Literal["RATED", "NO_AGREEMENT", "STAGES_NOT_SUPPORTED", "NO_RATE"]


class PeriodLine(BaseModel):
    journal_id: UUID
    project_name: str
    kind: Literal["INSTALLATION", "ADDON"]
    label: str
    work_date: date
    quantity: Decimal
    unit: str | None
    unit_price_ex_vat: Decimal | None
    amount_ex_vat: Decimal | None
    price_version: int | None
    agreement_id: UUID | None
    reason: LineReason


class PeriodSummary(BaseModel):
    start: date
    end: date
    signed_journals: int
    rated_lines: int
    unrated_lines: int
    amount_ex_vat: Decimal
    blocked_reason: Literal["MULTIPLE_CONTRACTS"] | None = None
    # VAT is deliberately not computed: the rate and the tax moment await the accountant (spec 12).
    vat: None = None
    estimate_only: Literal[True] = True


class PeriodPage(BaseModel):
    items: list[PeriodSummary]
    cutover: date
    today: date
    current_start: date
    undated_lines: int
    activation_enabled: bool
    estimate_only: Literal[True] = True


class PeriodDetail(PeriodSummary):
    lines: list[PeriodLine]
