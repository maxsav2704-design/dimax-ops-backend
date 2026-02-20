from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.v1.deps import CurrentUser, get_uow, require_admin
from app.modules.sync.application.health_service import SyncHealthService
from app.shared.infrastructure.db.uow_sqlalchemy import SqlAlchemyUnitOfWork

router = APIRouter(prefix="/admin/dashboard", tags=["Admin / Dashboard"])


@router.get("")
def get_dashboard(
    user: CurrentUser = Depends(require_admin),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
) -> dict:
    with uow:
        sync_health = SyncHealthService.run_for_company(
            uow, company_id=user.company_id
        )
        # сюда потом добавишь profit/kpi/projects/issues — сейчас возвращаем sync блок
        return {
            "sync_health": sync_health,
        }
