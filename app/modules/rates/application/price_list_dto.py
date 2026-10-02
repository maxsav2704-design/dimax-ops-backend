from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
Agreement = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class PriceListLineInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["DOOR", "ADDON"]
    target_id: UUID
    installer_price: Decimal = Field(gt=0, max_digits=12, decimal_places=2, allow_inf_nan=False)


class CreatePriceList(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    expected_latest_version: int = Field(ge=0, strict=True)
    reason: Reason
    agreement_reference: Agreement
    items: list[PriceListLineInput] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def unique_targets(self):
        keys = [(line.kind, line.target_id) for line in self.items]
        if len(set(keys)) != len(keys):
            raise ValueError("Each work type may appear only once")
        return self


class CancelPriceList(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Reason


class PriceListSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    version: int
    status: Literal["DRAFT", "CANCELLED"]
    currency: Literal["ILS"]
    reason: str
    agreement_reference: str
    created_by: UUID
    created_at: datetime
    cancelled_by: UUID | None
    cancelled_at: datetime | None
    cancellation_reason: str | None


class PriceListLine(BaseModel):
    kind: Literal["DOOR", "ADDON"]
    target_id: UUID
    name: str
    unit: str
    installer_price: Decimal


class PriceListDetail(PriceListSummary):
    items: list[PriceListLine]


class PriceListPage(BaseModel):
    items: list[PriceListSummary]
    total: int
    latest_version: int
