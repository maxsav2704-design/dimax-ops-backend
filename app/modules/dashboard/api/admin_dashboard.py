from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.v1.deps import CurrentUser, get_uow, require_admin
from app.modules.dashboard.api.schemas import DashboardResponseDTO
from app.modules.dashboard.application.service import DashboardService
from app.shared.infrastructure.db.uow_sqlalchemy import SqlAlchemyUnitOfWork

router = APIRouter(prefix="/admin/dashboard", tags=["Admin / Dashboard"])


@router.get("", response_model=DashboardResponseDTO)
def get_dashboard(
    user: CurrentUser = Depends(require_admin),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
) -> DashboardResponseDTO:
    with uow:
        return DashboardService.get_dashboard(uow, company_id=user.company_id)
