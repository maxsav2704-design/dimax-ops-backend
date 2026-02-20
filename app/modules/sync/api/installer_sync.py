from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.v1.acl import get_current_installer_id
from app.api.v1.deps import CurrentUser, get_uow, require_installer
from app.modules.sync.api.installer_schemas import (
    InstallerSyncRequest,
    InstallerSyncResponse,
    SyncAckItem,
    SyncChangeDTO,
)
from app.modules.sync.application.service import InstallerSyncService

router = APIRouter(prefix="/installer", tags=["Installer / Sync"])


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
