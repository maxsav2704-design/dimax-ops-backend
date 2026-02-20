from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.v1.deps import CurrentUser, get_uow, require_admin
from app.modules.doors.application.commands import (
    AdminOverrideDoor,
    MarkDoorInstalled,
    MarkDoorNotInstalled,
)
from app.modules.doors.application.use_cases import DoorUseCases
from app.modules.doors.api.schemas import (
    AdminOverrideBody,
    MarkNotInstalledBody,
    OkResponse,
)


router = APIRouter(prefix="/admin/doors", tags=["Admin / Doors"])


def _uuid(val: str) -> UUID:
    return UUID(val)


@router.post("/{door_id}/install", response_model=OkResponse)
def admin_mark_installed(
    door_id: str,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        DoorUseCases.mark_installed(
            uow,
            MarkDoorInstalled(
                company_id=user.company_id,
                actor_user_id=user.id,
                door_id=_uuid(door_id),
            ),
        )
    return OkResponse()


@router.post("/{door_id}/not-installed", response_model=OkResponse)
def admin_mark_not_installed(
    door_id: str,
    body: MarkNotInstalledBody,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        DoorUseCases.mark_not_installed(
            uow,
            MarkDoorNotInstalled(
                company_id=user.company_id,
                actor_user_id=user.id,
                door_id=_uuid(door_id),
                reason_id=body.reason_id,
                comment=body.comment,
            ),
        )
    return OkResponse()


@router.post("/{door_id}/override", response_model=OkResponse)
def admin_override(
    door_id: str,
    body: AdminOverrideBody,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        DoorUseCases.admin_override(
            uow,
            AdminOverrideDoor(
                company_id=user.company_id,
                actor_user_id=user.id,
                door_id=_uuid(door_id),
                new_status=body.new_status,
                reason_id=body.reason_id,
                comment=body.comment,
                override_reason=body.override_reason,
            ),
            actor_role=user.role,
        )
    return OkResponse()
