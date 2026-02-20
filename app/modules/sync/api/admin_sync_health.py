from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.v1.deps import CurrentUser, get_uow, require_admin
from app.modules.sync.application.health_service import SyncHealthService
from app.shared.infrastructure.db.uow_sqlalchemy import SqlAlchemyUnitOfWork

router = APIRouter(prefix="/admin/sync", tags=["Admin / Sync Health"])


@router.post("/health/run")
def run_health_check(
    user: CurrentUser = Depends(require_admin),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
) -> dict:
    with uow:
        data = SyncHealthService.run_for_company(
            uow, company_id=user.company_id
        )
        return {"ok": True, "data": data}


@router.get("/health/summary")
def get_health_summary(
    user: CurrentUser = Depends(require_admin),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
) -> dict:
    with uow:
        data = SyncHealthService.run_for_company(
            uow, company_id=user.company_id
        )
        return data
