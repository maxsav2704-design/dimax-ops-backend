from __future__ import annotations

import uuid

from fastapi import Depends

from app.api.v1.deps import CurrentUser, get_uow, require_installer
from app.shared.domain.errors import Forbidden


def get_current_installer_id(
    user: CurrentUser = Depends(require_installer),
    uow=Depends(get_uow),
) -> uuid.UUID:
    """
    Маппинг JWT user -> Installer.
    Если юзер INSTALLER, но в таблице installers нет связки user_id —
    значит он не привязан к монтажнику.
    """
    with uow:
        installer = uow.installers.get_by_user_id(
            company_id=user.company_id, user_id=user.id
        )
        if not installer:
            raise Forbidden(
                "Installer profile not linked to user. "
                "Ask admin to link installers.user_id"
            )
        return installer.id
