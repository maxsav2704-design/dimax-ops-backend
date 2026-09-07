from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class AddonTypeMini(BaseModel):
    id: UUID
    name: str
    unit: str
    default_client_price: Decimal
    default_installer_price: Decimal


class PlanItemDTO(BaseModel):
    id: UUID | None = None
    addon_type_id: UUID
    addon_name: str | None = None
    qty_planned: Decimal
    client_price: Decimal
    installer_price: Decimal
    notes: str | None = None


class FactItemDTO(BaseModel):
    id: UUID
    addon_type_id: UUID
    installer_id: UUID
    qty_done: Decimal
    done_at: datetime
    comment: str | None
    source: str


class AddonsSummaryItem(BaseModel):
    addon_type_id: UUID
    qty_planned: Decimal
    qty_done: Decimal
    revenue: Decimal
    payroll: Decimal
    profit: Decimal
    missing_plan: bool


class ProjectAddonsResponse(BaseModel):
    project_id: UUID
    types: list[AddonTypeMini]
    plan: list[PlanItemDTO]
    facts: list[FactItemDTO]
    summary: list[AddonsSummaryItem]


class PlanBatchBody(BaseModel):
    items: list[PlanItemDTO]


class ProjectAddonPlanListResponse(BaseModel):
    items: list[PlanItemDTO]


class UrgencySurchargeDTO(BaseModel):
    id: UUID
    scope: str
    order_number: str | None
    reason: str
    client_amount: Decimal
    installer_amount: Decimal
    effective_date: date | None
    notes: str | None


class UrgencySurchargeListResponse(BaseModel):
    items: list[UrgencySurchargeDTO]


class CreateUrgencySurchargeBody(BaseModel):
    scope: str
    order_number: str | None = None
    reason: str
    client_amount: Decimal
    installer_amount: Decimal
    effective_date: date | None = None
    notes: str | None = None


class OkResponse(BaseModel):
    ok: bool = True
