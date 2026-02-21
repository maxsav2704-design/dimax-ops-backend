from __future__ import annotations

from uuid import UUID

from app.modules.sync.api.admin_schemas import SyncStateDTO, SyncStatsDTO
from app.modules.sync.application.admin_service import AdminSyncStateService
from app.shared.domain.errors import NotFound


class AdminSyncApiService:
    @staticmethod
    def list_states(uow, *, company_id: UUID) -> list[SyncStateDTO]:
        items = AdminSyncStateService.list_states(uow, company_id=company_id)
        return [SyncStateDTO(**x) for x in items]

    @staticmethod
    def get_stats(uow, *, company_id: UUID) -> SyncStatsDTO:
        return SyncStatsDTO(
            **AdminSyncStateService.get_stats(uow, company_id=company_id)
        )

    @staticmethod
    def reset_state_for_user(
        uow,
        *,
        company_id: UUID,
        user_id: UUID,
    ) -> SyncStateDTO:
        result = AdminSyncStateService.reset_sync_state(
            uow,
            company_id=company_id,
            user_id=user_id,
        )
        if result is None:
            raise NotFound("Sync state not found")
        return SyncStateDTO(**result)

    @staticmethod
    def reset_state_legacy(
        uow,
        *,
        company_id: UUID,
        installer_id: UUID,
    ) -> dict:
        ok = AdminSyncStateService.reset_installer(
            uow,
            company_id=company_id,
            installer_id=installer_id,
        )
        if not ok:
            raise NotFound("Sync state not found")
        return {"status": "reset_ok"}
