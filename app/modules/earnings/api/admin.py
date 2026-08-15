from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.v1.deps import (
    CurrentUser,
    ensure_admin_can_view_rates,
    get_uow,
    require_admin,
)
from app.modules.earnings.api.admin_schemas import (
    AdminEarningsLedgerResponseDTO,
    EarningsCorrectionCreateDTO,
    EarningsCorrectionResponseDTO,
)
from app.modules.earnings.application.admin_api_service import EarningsAdminApiService


router = APIRouter(prefix="/admin/earnings", tags=["Admin / Earnings"])


@router.get(
    "/ledger/export",
    response_class=Response,
    responses={
        200: {
            "description": "CSV export",
            "content": {"text/csv": {"schema": {"type": "string"}}},
        }
    },
)
def export_earnings_ledger(
    installer_id: UUID | None = Query(default=None),
    project_id: UUID | None = Query(default=None),
    entry_type: Literal["ORIGINAL", "REVERSAL", "CORRECTION"] | None = Query(default=None),
    work_kind: Literal["DOOR", "ADDON"] | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    limit: int = Query(default=5000, ge=1, le=10000),
    offset: int = Query(default=0, ge=0),
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        ensure_admin_can_view_rates(uow, user)
        content = EarningsAdminApiService.ledger_export_csv(
            uow,
            company_id=user.company_id,
            installer_id=installer_id,
            project_id=project_id,
            entry_type=entry_type,
            work_kind=work_kind,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
        )
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"earnings_ledger_{ts}.csv"
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/ledger", response_model=AdminEarningsLedgerResponseDTO)
def list_earnings_ledger(
    installer_id: UUID | None = Query(default=None),
    project_id: UUID | None = Query(default=None),
    entry_type: Literal["ORIGINAL", "REVERSAL", "CORRECTION"] | None = Query(default=None),
    work_kind: Literal["DOOR", "ADDON"] | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
) -> AdminEarningsLedgerResponseDTO:
    with uow:
        ensure_admin_can_view_rates(uow, user)
        return EarningsAdminApiService.list_ledger(
            uow,
            company_id=user.company_id,
            installer_id=installer_id,
            project_id=project_id,
            entry_type=entry_type,
            work_kind=work_kind,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
        )


@router.post(
    "/corrections",
    response_model=EarningsCorrectionResponseDTO,
    status_code=status.HTTP_201_CREATED,
)
def create_earnings_correction(
    body: EarningsCorrectionCreateDTO,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
) -> EarningsCorrectionResponseDTO:
    with uow:
        ensure_admin_can_view_rates(uow, user)
        return EarningsAdminApiService.create_correction(
            uow,
            company_id=user.company_id,
            actor_user_id=user.id,
            completed_work_id=body.completed_work_id,
            rate_snapshot=body.rate_snapshot,
            reason=body.reason,
        )
