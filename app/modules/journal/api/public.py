from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.api.v1.deps import get_uow
from app.modules.journal.api.schemas import (
    OkResponse,
    PublicJournalGetResponse,
    PublicSignBody,
)
from app.modules.journal.application.public_api_service import (
    JournalPublicApiService,
)


router = APIRouter(prefix="/public/journals", tags=["Public / Journal"])


@router.get("/{token}", response_model=PublicJournalGetResponse)
def public_get(token: str, uow=Depends(get_uow)) -> PublicJournalGetResponse:
    with uow:
        return JournalPublicApiService.public_get(uow, token=token)


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
        JournalPublicApiService.public_sign(
            uow,
            token=token,
            signer_name=body.signer_name,
            signature_payload=body.signature_payload,
            ip=ip,
            user_agent=ua,
        )
    return OkResponse()
