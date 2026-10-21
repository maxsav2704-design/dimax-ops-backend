from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, model_validator

Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
StageCode = Annotated[str, StringConstraints(pattern=r"^([A-Z][A-Z0-9_]{0,39})?$")]


class CreateContractDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    factory_name: Label
    reference: Label
    reason: Reason


class ContractDraft(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    factory_name: str
    reference: str
    reason: str
    currency: Literal["ILS"]
    status: Literal["DRAFT"]
    is_demo: bool
    created_by: UUID
    created_at: datetime


class ContractPage(BaseModel):
    items: list[ContractDraft]
    total: int


class ContractTermsFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    factory_legal_name: Label
    registration_number: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    address: Reason
    contact_name: Label | None = None
    contact_email: Annotated[EmailStr, Field(max_length=254)] | None = None
    contact_phone: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=40,
                                                  pattern=r"^\+?[0-9 ()-]+$")] | None = None
    proposed_from: date
    proposed_until: date | None = None
    billing_basis: Literal["FULL_INSTALLATION", "STAGES"]
    payment_terms: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    retention_terms: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    reason: Reason
    agreement_reference: Label

    @model_validator(mode="after")
    def ordered_dates(self):
        if self.proposed_until is not None and self.proposed_until < self.proposed_from:
            raise ValueError("Proposed end cannot precede proposed start")
        if self.contact_phone is not None and not any(char.isdigit() for char in self.contact_phone):
            raise ValueError("Phone must contain digits")
        return self


class CreateContractTermsDraft(ContractTermsFields):
    request_id: UUID
    expected_latest_version: int = Field(ge=0, strict=True)


class ContractTermsSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    contract_id: UUID
    version: int
    status: Literal["DRAFT"]
    proposed_from: date
    proposed_until: date | None
    reason: str
    agreement_reference: str
    created_by: UUID
    created_by_name: str
    created_at: datetime
    is_demo: bool
    factory_confirmed: Literal[False] = False
    usable_for_billing: Literal[False] = False
    currency: Literal["ILS"] = "ILS"
    vat_basis: Literal["EXCLUSIVE"] = "EXCLUSIVE"
    period_start_day: Literal[10] = 10
    period_timezone: Literal["Asia/Jerusalem"] = "Asia/Jerusalem"


class ContractTermsDetail(ContractTermsSummary, ContractTermsFields):
    pass


class ContractTermsPage(BaseModel):
    items: list[ContractTermsSummary]
    total: int
    latest_version: int


class CommercialLineInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["INSTALLATION", "STAGE", "ADDON"]
    target_id: UUID
    stage_code: StageCode = ""
    unit_price_ex_vat: Decimal = Field(
        ge=0, max_digits=12, decimal_places=2, allow_inf_nan=False,
    )

    @model_validator(mode="after")
    def validate_stage(self):
        if (self.kind == "STAGE") != bool(self.stage_code):
            raise ValueError("Only STAGE lines require a stage code")
        return self


class CreateCommercialPriceDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    expected_latest_version: int = Field(ge=0, strict=True)
    proposed_from: date
    reason: Reason
    agreement_reference: Label
    items: list[CommercialLineInput] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def unique_lines(self):
        keys = [(line.kind, line.target_id, line.stage_code) for line in self.items]
        if len(set(keys)) != len(keys):
            raise ValueError("Each work/stage may appear only once")
        return self


class CommercialLine(CommercialLineInput):
    name: str
    unit: str


class CommercialPriceSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    contract_id: UUID
    version: int
    status: Literal["DRAFT"]
    proposed_from: date
    reason: str
    agreement_reference: str
    created_by: UUID
    created_at: datetime
    currency: Literal["ILS"] = "ILS"
    vat_basis: Literal["EXCLUSIVE"] = "EXCLUSIVE"
    factory_confirmed: Literal[False] = False
    usable_for_billing: Literal[False] = False
    is_demo: bool


class CommercialPriceDetail(CommercialPriceSummary):
    items: list[CommercialLine]


class CommercialPricePage(BaseModel):
    items: list[CommercialPriceSummary]
    total: int
    latest_version: int
