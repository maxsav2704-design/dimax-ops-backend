from __future__ import annotations

import uuid
from decimal import Decimal

from pydantic import BaseModel


class InstallerEarningsByInstallTypeDTO(BaseModel):
    install_type: str
    total: Decimal


class InstallerEarningsByProjectDTO(BaseModel):
    project_id: uuid.UUID | None
    project_name: str
    total: Decimal


class InstallerEarningsWeeklyBreakdownDTO(BaseModel):
    week_start: str
    total: Decimal


class InstallerEarningsSummaryDTO(BaseModel):
    total: Decimal
    jobs_count: int
    by_install_type: list[InstallerEarningsByInstallTypeDTO]
    by_project: list[InstallerEarningsByProjectDTO]
    weekly_breakdown: list[InstallerEarningsWeeklyBreakdownDTO] = []
