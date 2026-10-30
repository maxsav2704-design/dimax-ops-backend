from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StrictBool, field_validator

from app.modules.rates.application.price_list_dto import Reason
from app.modules.rates.application.installer_price_dto import InstallerPriceSnapshot
from app.shared.domain.errors import ValidationError


class ActivatePriceVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    expected_active_price_list_id: UUID | None
    reason: Reason
    reviewed_transition: StrictBool

    @field_validator("reviewed_transition")
    @classmethod
    def require_review(cls, value: bool) -> bool:
        if not value:
            raise ValueError("The legacy-price transition must be explicitly reviewed")
        return value


class EffectivePriceVersion(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    price_list_id: UUID
    approval_id: UUID
    effective_from: datetime
    created_by: UUID
    reason: str


class CompanyPricingState(BaseModel):
    mode: Literal["LEGACY", "FACTORY"]
    active_price: InstallerPriceSnapshot | None


class FactoryWorkPriceContext(BaseModel):
    """Verified timeline and work identity, without assuming a rate exists."""

    model_config = ConfigDict(frozen=True)
    price_list_id: UUID
    version: int
    approval_id: UUID
    activation_id: UUID
    kind: Literal["DOOR", "ADDON", "STAGE"]
    target_id: UUID
    stage_code: str | None = None
    currency: Literal["ILS"]
    performed_at: datetime
    effective_from: datetime
    selection: Literal["AT_EXECUTION", "FIRST_CONFIRMED_LEGACY"]
    snapshot_hash: str


class FactoryPriceQuote(FactoryWorkPriceContext):
    price_list_item_id: UUID
    unit: str
    rate: Decimal

    def amount(self, quantity: Decimal) -> Decimal:
        return work_price_amount(self.kind, self.rate, quantity)


def work_price_amount(kind: str, rate: Decimal, quantity: Decimal) -> Decimal:
    """Same decimal limits and rounding for a price quote and a proposed work price."""
    try:
        quantity = Decimal(str(quantity))
        if not quantity.is_finite() or not 0 < quantity <= Decimal("9999999999.99") or quantity != quantity.quantize(Decimal("0.01")):
            raise ValueError
        if kind not in ("DOOR", "ADDON", "STAGE") or (kind in ("DOOR", "STAGE") and quantity != 1):
            raise ValueError
        amount = (quantity * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if not 0 < amount <= Decimal("9999999999.99"):
            raise ValueError
        return amount
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError("Invalid quantity or resulting factory work amount", field="quantity") from None
