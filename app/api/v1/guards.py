from __future__ import annotations

import uuid

from fastapi import Depends

from app.api.v1.acl import get_current_installer_id
from app.api.v1.deps import CurrentUser, get_uow, require_installer
from app.shared.domain.errors import Forbidden, NotFound


def require_door_owned_by_installer(
    door_id: uuid.UUID,
    user: CurrentUser = Depends(require_installer),
    installer_id: uuid.UUID = Depends(get_current_installer_id),
    uow=Depends(get_uow),
) -> uuid.UUID:
    """
    Возвращает installer_id, если дверь принадлежит монтажнику.
    """
    with uow:
        door = uow.doors.get(company_id=user.company_id, door_id=door_id)
        if not door:
            raise NotFound(
                "Door not found", details={"door_id": str(door_id)}
            )

        if door.installer_id != installer_id:
            raise Forbidden("Door is not assigned to this installer")

    return installer_id
