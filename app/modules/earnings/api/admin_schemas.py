from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class EarningsCorrectionCreateDTO(BaseModel):
    completed_work_id: uuid.UUID
    rate_snapshot: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    reason: str = Field(min_length=1, max_length=1000)


class EarningsLedgerEntryDTO(BaseModel):
    id: uuid.UUID
    entry_type: str
    correction_ref_id: uuid.UUID | None
    completed_at: datetime
    quantity: Decimal
    rate_snapshot: Decimal
    amount_snapshot: Decimal
    reason: str | None


class EarningsCorrectionResponseDTO(BaseModel):
    original: EarningsLedgerEntryDTO
    reversal: EarningsLedgerEntryDTO
    correction: EarningsLedgerEntryDTO


class FactoryEarningPriceDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    price_list_id: uuid.UUID
    price_list_item_id: uuid.UUID
    approval_id: uuid.UUID
    activation_id: uuid.UUID
    version: int
    selection: str
    unit: str
    currency: str
    confirmed_rate: Decimal
    performed_at: datetime
    effective_from: datetime


class WorkEarningPriceDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    approval_id: uuid.UUID
    completed_work_id: uuid.UUID
    approval_hash: str
    amount: Decimal
    accrued_at: datetime
    reason: str


class AdminEarningsLedgerItemDTO(EarningsLedgerEntryDTO):
    work_kind: str
    project_id: uuid.UUID | None
    project_name: str | None
    door_id: uuid.UUID | None
    door_label: str | None
    door_code: str | None
    addon_fact_id: uuid.UUID | None
    addon_type_id: uuid.UUID | None = None
    addon_type_name: str | None = None
    addon_comment: str | None = None
    stage_fact_id: uuid.UUID | None = None
    stage_code: str | None = None
    installer_id: uuid.UUID
    installer_name: str | None
    can_correct: bool
    factory_price: FactoryEarningPriceDTO | None = None
    work_price: WorkEarningPriceDTO | None = None


class AdminEarningsLedgerResponseDTO(BaseModel):
    items: list[AdminEarningsLedgerItemDTO]
    total: int
    limit: int
    offset: int
