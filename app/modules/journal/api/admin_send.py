from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.v1.deps import CurrentUser, get_uow, require_admin
from app.modules.journal.api.send_schemas import SendJournalBody
from app.modules.journal.application.send_service import JournalSendService


router = APIRouter(prefix="/admin/journals", tags=["Admin / Journal"])


@router.post("/{journal_id}/send")
def send_journal(
    journal_id: UUID,
    body: SendJournalBody,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        result = JournalSendService.enqueue_send(
            uow,
            company_id=user.company_id,
            journal_id=journal_id,
            email_to=str(body.email_to) if body.email_to else None,
            whatsapp_to=body.whatsapp_to,
            subject=body.subject,
            message=body.message,
            send_email=body.send_email,
            send_whatsapp=body.send_whatsapp,
        )
        return result
