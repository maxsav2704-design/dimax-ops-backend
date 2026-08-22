from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.modules.journal.application.submission_policy import (
    JournalSubmissionPolicy,
)
from app.modules.journal.application.use_cases import JournalUseCases
from app.modules.journal.domain.enums import JournalDeliveryStatus
from app.modules.outbox.domain.enums import OutboxChannel, OutboxStatus
from app.modules.outbox.infrastructure.models import OutboxMessageORM
from app.shared.infrastructure.observability import get_logger, log_event


logger = get_logger(__name__)


class JournalSignedDeliveryService:
    @staticmethod
    def enqueue(uow, *, journal) -> dict:
        project = uow.projects.get(
            company_id=journal.company_id,
            project_id=journal.project_id,
        )
        if project is None:
            return {"queued": False, "recipient_count": 0}

        readiness = JournalSubmissionPolicy.evaluate(
            uow,
            journal=journal,
            project=project,
        )
        developer_email = readiness.developer_email
        admin_emails = [
            email for email in readiness.admin_emails if email != developer_email
        ]
        recipients = ([developer_email] if developer_email else []) + admin_emails
        recipients = list(dict.fromkeys(recipients))
        if not readiness.can_submit:
            error = "Signed journal requires completed work and valid developer and administrator emails"
            uow.journals.set_email_status(
                company_id=journal.company_id,
                journal_id=journal.id,
                status=JournalDeliveryStatus.FAILED,
                error=error,
            )
            log_event(
                logger,
                "journal.signed_delivery.skipped",
                level="warning",
                company_id=journal.company_id,
                journal_id=journal.id,
                reason=error,
            )
            return {"queued": False, "recipient_count": 0}

        assert developer_email is not None
        pdf_file = JournalUseCases.export_pdf(
            uow,
            company_id=journal.company_id,
            journal_id=journal.id,
        )
        to_email = developer_email
        cc_emails = [email for email in recipients if email != to_email]
        project_label = project.name or str(project.id)
        subject = f"DIMAX signed work acceptance - {project_label}"
        body = (
            f"The work acceptance document for {project_label} has been signed "
            f"by {journal.signer_name}.\n\n"
            "The signed PDF is attached. This message was generated automatically "
            "by DIMAX Operations Suite."
        )
        message = OutboxMessageORM(
            company_id=journal.company_id,
            channel=OutboxChannel.EMAIL,
            status=OutboxStatus.PENDING,
            correlation_id=journal.id,
            payload={
                "to_email": to_email,
                "cc_emails": cc_emails,
                "subject": subject,
                "body_text": body,
                "object_key": pdf_file.file_path,
                "attachment_name": f"dimax_acceptance_{str(journal.id)[:8]}.pdf",
                "delivery_reason": "SIGNED_JOURNAL",
            },
            attempts=0,
            max_attempts=5,
            scheduled_at=datetime.now(timezone.utc),
        )
        uow.outbox.enqueue(message)
        uow.journals.set_email_status(
            company_id=journal.company_id,
            journal_id=journal.id,
            status=JournalDeliveryStatus.PENDING,
            sent_at=None,
            error=None,
        )
        log_event(
            logger,
            "journal.signed_delivery.enqueued",
            company_id=journal.company_id,
            journal_id=journal.id,
            outbox_id=message.id,
            recipient_count=len(recipients),
        )
        return {"queued": True, "recipient_count": len(recipients)}
