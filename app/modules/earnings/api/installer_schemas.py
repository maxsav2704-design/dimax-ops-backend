from __future__ import annotations

import uuid
from decimal import Decimal

from pydantic import BaseModel


class InstallerEarningsByInstallTypeDTO(BaseModel):
    install_type: str
    total: Decimal
    amount: Decimal


class InstallerEarningsByProjectDTO(BaseModel):
    project_id: uuid.UUID | None
    project_name: str
    total: Decimal
    amount: Decimal


class InstallerEarningsWeeklyBreakdownDTO(BaseModel):
    week_start: str
    total: Decimal


class InstallerEarningsDayDTO(BaseModel):
    date: str
    amount: Decimal
    jobs_count: int


class InstallerEarningsInstallTypeSummaryDTO(BaseModel):
    code: str
    label: str
    amount: Decimal
    quantity: int


class InstallerEarningsRowDTO(BaseModel):
    id: uuid.UUID
    work_date: str
    project_id: uuid.UUID | None
    project_name: str | None
    door_label: str | None
    install_type_code: str
    install_type_label: str
    quantity: Decimal
    rate: Decimal
    amount: Decimal


class InstallerEarningsSummaryDTO(BaseModel):
    total: Decimal
    jobs_count: int
    by_install_type: list[InstallerEarningsByInstallTypeDTO]
    by_project: list[InstallerEarningsByProjectDTO]
    weekly_breakdown: list[InstallerEarningsWeeklyBreakdownDTO] = []
    currency: str = "ILS"
    today_total: Decimal
    month_total: Decimal
    by_day: list[InstallerEarningsDayDTO] = []
    period_key: str
    days: list[InstallerEarningsDayDTO] = []
    install_types: list[InstallerEarningsInstallTypeSummaryDTO] = []
    rows: list[InstallerEarningsRowDTO] = []
    generated_at: str | None = None
