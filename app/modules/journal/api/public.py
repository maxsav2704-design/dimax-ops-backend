from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.api.v1.deps import get_uow
from app.modules.journal.api.schemas import OkResponse, PublicSignBody
from app.modules.journal.application.use_cases import JournalUseCases
from app.modules.journal.infrastructure.models import JournalDoorItemORM


router = APIRouter(prefix="/public/journals", tags=["Public / Journal"])


def _status_value(s) -> str:
    return s.value if hasattr(s, "value") else str(s)


@router.get("/{token}")
def public_get(token: str, uow=Depends(get_uow)):
    with uow:
        j = JournalUseCases.public_get(uow, token=token)

        items = (
            uow.session.query(JournalDoorItemORM)
            .filter(
                JournalDoorItemORM.company_id == j.company_id,
                JournalDoorItemORM.journal_id == j.id,
            )
            .order_by(JournalDoorItemORM.unit_label.asc())
            .all()
        )

        return {
            "journal": {
                "id": str(j.id),
                "project_id": str(j.project_id),
                "status": _status_value(j.status),
                "title": j.title,
                "notes": j.notes,
                "lock_header": j.lock_header,
                "lock_table": j.lock_table,
                "lock_footer": j.lock_footer,
                "signed_at": (
                    j.signed_at.isoformat() if j.signed_at else None
                ),
                "signer_name": j.signer_name,
                "snapshot_version": j.snapshot_version,
            },
            "items": [
                {
                    "unit_label": it.unit_label,
                    "door_type_id": str(it.door_type_id),
                    "installed_at": (
                        it.installed_at.isoformat()
                        if it.installed_at
                        else None
                    ),
                }
                for it in items
            ],
        }


@router.post("/{token}/sign", response_model=OkResponse)
def public_sign(
    token: str,
    body: PublicSignBody,
    request: Request,
    uow=Depends(get_uow),
):
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")

    with uow:
        JournalUseCases.public_sign(
            uow,
            token=token,
            signer_name=body.signer_name,
            signature_payload=body.signature_payload,
            ip=ip,
            user_agent=ua,
        )
    return OkResponse()
