from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.v1.acl import get_current_installer_id
from app.api.v1.deps import CurrentUser, require_installer
from app.modules.ai.api.routes import register_ai_routes


router = APIRouter(prefix="/installer/ai", tags=["Installer / DIMAX AI"])


def require_ai_installer(user: CurrentUser = Depends(require_installer),
                         _installer_id=Depends(get_current_installer_id)) -> CurrentUser:
    # An installer linked to an installer record. Tools see only that installer's
    # positions; installation facts, prices and earnings are never agent actions.
    return user


register_ai_routes(router, require_ai_installer)
