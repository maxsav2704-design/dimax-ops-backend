from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.v1.acl import get_current_installer_id
from app.api.v1.deps import CurrentUser, get_uow, require_installer
from app.modules.earnings.api.installer_schemas import InstallerEarningsSummaryDTO
from app.modules.earnings.application.installer_api_service import (
    InstallerEarningsApiService,
)


router = APIRouter(prefix="/installer/earnings", tags=["Installer / Earnings"])


@router.get("/summary", response_model=InstallerEarningsSummaryDTO)
def installer_earnings_summary(
    period: str = Query(default="day", pattern="^(day|week|month)$"),
    date_value: date | None = Query(default=None, alias="date"),
    user: CurrentUser = Depends(require_installer),
    installer_id: UUID = Depends(get_current_installer_id),
    uow=Depends(get_uow),
):
    with uow:
        return InstallerEarningsApiService.summary(
            uow,
            company_id=user.company_id,
            installer_id=installer_id,
            period=period,
            anchor_date=date_value,
        )
