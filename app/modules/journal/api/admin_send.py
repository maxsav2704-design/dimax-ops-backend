from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.v1.deps import CurrentUser, get_uow, require_admin
from app.modules.audit.application.service import AuditService
from app.modules.journal.api.send_schemas import (
    SendJournalBody,
    SendJournalResponse,
)
from app.modules.journal.application.send_service import JournalSendService


router = APIRouter(prefix="/admin/journals", tags=["Admin / Journal"])


@router.post("/{journal_id}/send", response_model=SendJournalResponse)
def send_journal(
    journal_id: UUID,
    body: SendJournalBody,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
) -> SendJournalResponse:
    with uow:
        journal_before = uow.journals.get(
            company_id=user.company_id,
            journal_id=journal_id,
        )
        before_state = {
            "email_delivery_status": (
                str(journal_before.email_delivery_status.value)
                if journal_before is not None
                else None
            ),
            "whatsapp_delivery_status": (
                str(journal_before.whatsapp_delivery_status.value)
                if journal_before is not None
                else None
            ),
        }
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
        journal_after = uow.journals.get(
            company_id=user.company_id,
            journal_id=journal_id,
        )
        if journal_after is not None:
            AuditService.add(
                uow,
                company_id=user.company_id,
                actor_user_id=user.id,
                entity_type="journal",
                entity_id=journal_id,
                action="JOURNAL_SEND_REQUESTED",
                before=before_state,
                after={
                    "email_delivery_status": str(
                        journal_after.email_delivery_status.value
                    ),
                    "whatsapp_delivery_status": str(
                        journal_after.whatsapp_delivery_status.value
                    ),
                    "enqueued": result.get("enqueued"),
                    "outbox_ids": result.get("outbox_ids"),
                },
            )
        return result
