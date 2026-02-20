from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class KpiResponse(BaseModel):
    period_from: datetime | None
    period_to: datetime | None

    installed_doors: int
    not_installed_doors: int

    payroll_total: Decimal
    revenue_total: Decimal
    profit_total: Decimal

    problem_projects: int

    missing_rates_installed_doors: int
    missing_addon_plans_done: int


class DashboardResponse(BaseModel):
    kpi: KpiResponse
    sync_health: dict


class ProblemProjectItem(BaseModel):
    project_id: UUID
    name: str
    address: str
    not_installed_doors: int


class ProblemProjectsResponse(BaseModel):
    items: list[ProblemProjectItem]


class TopReasonItem(BaseModel):
    reason_id: UUID | None
    reason_name: str
    count: int


class TopReasonsResponse(BaseModel):
    items: list[TopReasonItem]


class ProjectProfitResponse(BaseModel):
    project_id: UUID
    installed_doors: int
    payroll_total: Decimal
    revenue_total: Decimal
    profit_total: Decimal
    missing_rates_installed_doors: int


class DeliveryStatsResponse(BaseModel):
    period_from: datetime | None
    period_to: datetime | None

    whatsapp_pending: int
    whatsapp_delivered: int
    whatsapp_failed: int

    email_sent: int
    email_failed: int
