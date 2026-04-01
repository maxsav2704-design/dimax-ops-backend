from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.v1.acl import get_current_installer_id
from app.api.v1.deps import CurrentUser, get_uow, require_installer
from app.api.v1.guards import require_door_owned_by_installer
from app.modules.doors.application.installer_service import InstallerDoorService
from app.modules.doors.application.commands import (
    MarkDoorInstalled,
    MarkDoorNotInstalled,
)
from app.modules.doors.domain.enums import DoorStatus
from app.modules.doors.application.use_cases import DoorUseCases
from app.modules.doors.api.schemas import (
    InstallerDoorStatusUpdateBody,
    InstallerDoorStatusUpdateResponse,
    MarkNotInstalledBody,
    OkResponse,
)


router = APIRouter(prefix="/installer/doors", tags=["Installer / Doors"])


@router.patch("/{door_id}/status", response_model=InstallerDoorStatusUpdateResponse)
def installer_change_status(
    door_id: UUID,
    body: InstallerDoorStatusUpdateBody,
    user: CurrentUser = Depends(require_installer),
    installer_id: UUID = Depends(get_current_installer_id),
    uow=Depends(get_uow),
):
    with uow:
        return InstallerDoorService.change_status(
            uow,
            company_id=user.company_id,
            actor_user_id=user.id,
            installer_id=installer_id,
            door_id=door_id,
            to_status=DoorStatus(body.status),
        )


@router.post("/{door_id}/install", response_model=OkResponse)
def installer_mark_installed(
    door_id: UUID,
    user: CurrentUser = Depends(require_installer),
    _installer_id: UUID = Depends(require_door_owned_by_installer),
    uow=Depends(get_uow),
):
    with uow:
        DoorUseCases.mark_installed(
            uow,
            MarkDoorInstalled(
                company_id=user.company_id,
                actor_user_id=user.id,
                door_id=door_id,
            ),
        )
    return OkResponse()


@router.post("/{door_id}/not-installed", response_model=OkResponse)
def installer_mark_not_installed(
    door_id: UUID,
    body: MarkNotInstalledBody,
    user: CurrentUser = Depends(require_installer),
    _installer_id: UUID = Depends(require_door_owned_by_installer),
    uow=Depends(get_uow),
):
    with uow:
        DoorUseCases.mark_not_installed(
            uow,
            MarkDoorNotInstalled(
                company_id=user.company_id,
                actor_user_id=user.id,
                door_id=door_id,
                reason_id=body.reason_id,
                comment=body.comment,
            ),
        )
    return OkResponse()
