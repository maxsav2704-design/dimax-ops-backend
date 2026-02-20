from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.v1.deps import CurrentUser, get_uow, require_installer
from app.api.v1.guards import require_door_owned_by_installer
from app.modules.doors.application.commands import (
    MarkDoorInstalled,
    MarkDoorNotInstalled,
)
from app.modules.doors.application.use_cases import DoorUseCases
from app.modules.doors.api.schemas import MarkNotInstalledBody, OkResponse


router = APIRouter(prefix="/installer/doors", tags=["Installer / Doors"])


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
