from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.v1.deps import get_uow, require_admin
from app.api.v1.deps import CurrentUser
from app.modules.sync.api.admin_schemas import (
    SyncResetLegacyResponse,
    SyncStateDTO,
    SyncStatsDTO,
)
from app.modules.sync.application.admin_api_service import AdminSyncApiService
from app.shared.infrastructure.db.uow_sqlalchemy import SqlAlchemyUnitOfWork

router = APIRouter(prefix="/admin/sync", tags=["Admin Sync"])


@router.get("/states", response_model=list[SyncStateDTO])
def list_sync_states(
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    admin: CurrentUser = Depends(require_admin),
) -> list[SyncStateDTO]:
    with uow:
        return AdminSyncApiService.list_states(
            uow,
            company_id=admin.company_id,
        )


@router.get("/stats", response_model=SyncStatsDTO)
def get_sync_stats(
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    admin: CurrentUser = Depends(require_admin),
) -> SyncStatsDTO:
    with uow:
        return AdminSyncApiService.get_stats(
            uow,
            company_id=admin.company_id,
        )


@router.post(
    "/states/{installer_id}/reset",
    response_model=SyncStateDTO,
    summary="Reset sync state for installer",
    description="Resets sync state for the given installer (user with role INSTALLER). installer_id = user id. Returns updated SyncStateDTO.",
)
def reset_sync_state_for_installer(
    installer_id: UUID,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    admin: CurrentUser = Depends(require_admin),
) -> SyncStateDTO:
    with uow:
        return AdminSyncApiService.reset_state_for_user(
            uow,
            company_id=admin.company_id,
            user_id=installer_id,
        )


@router.post("/reset/{installer_id}", response_model=SyncResetLegacyResponse)
def reset_sync_state_legacy(
    installer_id: UUID,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    admin: CurrentUser = Depends(require_admin),
) -> SyncResetLegacyResponse:
    with uow:
        return AdminSyncApiService.reset_state_legacy(
            uow,
            company_id=admin.company_id,
            installer_id=installer_id,
        )
