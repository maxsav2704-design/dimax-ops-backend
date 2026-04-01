from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.v1.acl import get_current_installer_id
from app.api.v1.pagination import paginate_items, pagination_params
from app.api.v1.deps import CurrentUser, get_uow, require_installer
from app.modules.sync.api.installer_schemas import (
    InstallerSyncRequest,
    InstallerSyncResponse,
    InstallerSyncQueueItemDTO,
    InstallerSyncQueueListResponse,
    SyncAckItem,
    SyncChangeDTO,
)
from app.modules.sync.application.service import InstallerSyncService

router = APIRouter(prefix="/installer", tags=["Installer / Sync"])


@router.get("/sync-queue", response_model=InstallerSyncQueueListResponse)
def list_sync_queue(
    pagination: tuple[int, int] = Depends(pagination_params),
    user: CurrentUser = Depends(require_installer),
    uow=Depends(get_uow),
):
    page, per_page = pagination
    with uow:
        rows = uow.sync_queue.list_for_user(
            company_id=user.company_id,
            user_id=user.id,
        )
        items = [
            InstallerSyncQueueItemDTO(
                id=row.id,
                entity_type=row.entity_type,
                entity_id=row.entity_id,
                operation_type=row.operation_type,
                payload=row.payload or {},
                base_version=row.base_version,
                status=row.status,
                conflict_code=row.conflict_code,
                created_at=row.created_at,
                synced_at=row.synced_at,
            )
            for row in rows
        ]
        return InstallerSyncQueueListResponse(**paginate_items(items, page=page, per_page=per_page))


@router.post("/sync", response_model=InstallerSyncResponse)
def sync(
    body: InstallerSyncRequest,
    user: CurrentUser = Depends(require_installer),
    installer_id: UUID = Depends(get_current_installer_id),
    uow=Depends(get_uow),
):
    with uow:
        res = InstallerSyncService.sync_v2(
            uow,
            company_id=user.company_id,
            installer_id=installer_id,
            actor_user_id=user.id,
            since_cursor=body.since_cursor,
            ack_cursor=body.ack_cursor,
            app_version=body.app_version,
            device_id=body.device_id,
            events=[e.model_dump() for e in body.events],
        )

        return InstallerSyncResponse(
            server_time=res["server_time"],
            next_cursor=res["next_cursor"],
            reset_required=res.get("reset_required", False),
            snapshot=res.get("snapshot"),
            acks=[SyncAckItem(**x) for x in res["acks"]],
            changes=[SyncChangeDTO(**x) for x in res["changes"]],
        )
