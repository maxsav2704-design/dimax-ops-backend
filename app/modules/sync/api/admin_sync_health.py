from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.v1.deps import CurrentUser, get_uow, require_admin
from app.modules.sync.api.admin_schemas import (
    SyncHealthRunResponseDTO,
    SyncHealthSummaryDTO,
)
from app.modules.sync.application.admin_health_api_service import (
    AdminSyncHealthApiService,
)
from app.shared.infrastructure.db.uow_sqlalchemy import SqlAlchemyUnitOfWork

router = APIRouter(prefix="/admin/sync", tags=["Admin / Sync Health"])


@router.post("/health/run", response_model=SyncHealthRunResponseDTO)
def run_health_check(
    user: CurrentUser = Depends(require_admin),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
) -> SyncHealthRunResponseDTO:
    with uow:
        return AdminSyncHealthApiService.run_health_check(
            uow,
            company_id=user.company_id,
        )


@router.get("/health/summary", response_model=SyncHealthSummaryDTO)
def get_health_summary(
    user: CurrentUser = Depends(require_admin),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
) -> SyncHealthSummaryDTO:
    with uow:
        return AdminSyncHealthApiService.get_health_summary(
            uow,
            company_id=user.company_id,
        )
