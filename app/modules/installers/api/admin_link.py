from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.v1.deps import CurrentUser, get_uow, require_admin
from app.shared.domain.errors import NotFound


router = APIRouter(prefix="/admin/installers", tags=["Admin / Installers"])


class LinkUserBody(BaseModel):
    user_id: UUID


@router.post("/{installer_id}/link-user")
def link_user(
    installer_id: UUID,
    body: LinkUserBody,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        inst = uow.installers.get(
            company_id=user.company_id, installer_id=installer_id
        )
        if not inst:
            raise NotFound(
                "Installer not found",
                details={"installer_id": str(installer_id)},
            )

        inst.user_id = body.user_id
        uow.session.add(inst)
    return {"ok": True}
