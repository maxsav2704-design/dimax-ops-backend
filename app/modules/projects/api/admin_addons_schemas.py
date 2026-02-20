from __future__ import annotations

from datetime import datetime
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
    addon_type_id: UUID
    qty_planned: Decimal
    client_price: Decimal
    installer_price: Decimal


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
