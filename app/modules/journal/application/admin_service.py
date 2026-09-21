from __future__ import annotations

import uuid

from app.core.config import settings
from app.modules.audit.application.service import AuditService
from app.modules.journal.api.schemas import (
    JournalCreateResponse,
    JournalExportPdfResponse,
    JournalMarkReadyResponse,
)
from app.modules.journal.application.use_cases import JournalUseCases
from app.modules.journal.application.signing_links import journal_signing_url
from app.modules.journal.application.snapshot import read_journal_snapshot
from app.modules.journal.application.submission_policy import (
    JournalSubmissionPolicy,
)
from app.shared.domain.errors import Conflict, NotFound


def _status_value(s) -> str:
    return s.value if hasattr(s, "value") else str(s)


class JournalAdminService:
    @staticmethod
    def get_snapshot(uow, *, company_id: uuid.UUID, journal_id: uuid.UUID) -> dict:
        journal = uow.journals.get(company_id=company_id, journal_id=journal_id)
        if journal is None:
            raise NotFound("Journal not found")
        result = read_journal_snapshot(uow, journal=journal)
        result["signing_url"] = journal_signing_url(journal)
        return result

    @staticmethod
    def list_journals(
        uow,
        *,
        company_id: uuid.UUID,
        status: str | None,
        limit: int,
        offset: int,
    ) -> dict:
        items = uow.journals.list(
            company_id=company_id,
            status=status,
            limit=limit,
            offset=offset,
        )
        return {
            "items": [
                {
                    "id": str(j.id),
                    "project_id": str(j.project_id),
                    "status": _status_value(j.status),
                    "title": j.title,
                    "signed_at": (
                        j.signed_at.isoformat() if j.signed_at else None
                    ),
                }
                for j in items
            ]
        }

    @staticmethod
    def create_draft(
        uow,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID,
        title: str | None,
        pdf_locale: str = "en",
    ) -> JournalCreateResponse:
        j = JournalUseCases.create_draft(
            uow,
            company_id=company_id,
            project_id=project_id,
            title=title,
            pdf_locale=pdf_locale,
        )
        return JournalCreateResponse(id=j.id)

    @staticmethod
    def get_journal(
        uow,
        *,
        company_id: uuid.UUID,
        journal_id: uuid.UUID,
    ) -> dict:
        j = uow.journals.get(company_id=company_id, journal_id=journal_id)
        if not j:
            raise NotFound("Journal not found")

        return {
            "id": str(j.id),
            "project_id": str(j.project_id),
            "status": _status_value(j.status),
            "title": j.title,
            "notes": j.notes,
            "pdf_locale": j.pdf_locale,
            "public_token": j.public_token,
            "public_token_expires_at": j.public_token_expires_at,
            "lock_header": j.lock_header,
            "lock_table": j.lock_table,
            "lock_footer": j.lock_footer,
            "signed_at": j.signed_at.isoformat() if j.signed_at else None,
            "signer_name": j.signer_name,
            "snapshot_version": j.snapshot_version,
            "email_delivery_status": _status_value(j.email_delivery_status),
            "whatsapp_delivery_status": _status_value(
                j.whatsapp_delivery_status
            ),
            "email_last_sent_at": j.email_last_sent_at,
            "whatsapp_last_sent_at": j.whatsapp_last_sent_at,
            "whatsapp_delivered_at": j.whatsapp_delivered_at,
            "email_last_error": j.email_last_error,
            "whatsapp_last_error": j.whatsapp_last_error,
        }

    @staticmethod
    def update_journal(
        uow,
        *,
        company_id: uuid.UUID,
        journal_id: uuid.UUID,
        title: str | None,
        notes: str | None,
        lock_header: bool | None,
        lock_table: bool | None,
        lock_footer: bool | None,
        pdf_locale: str | None = None,
        actor_user_id: uuid.UUID | None = None,
    ) -> None:
        j = uow.journals.get(company_id=company_id, journal_id=journal_id, for_update=True)
        if not j:
            raise NotFound("Journal not found")

        if _status_value(j.status) != "DRAFT":
            raise Conflict("Only DRAFT journal can be edited")

        if pdf_locale is not None and pdf_locale != j.pdf_locale:
            if j.lock_header:
                raise Conflict("Journal header is locked")
            if actor_user_id is not None:
                AuditService.add(
                    uow, company_id=company_id, actor_user_id=actor_user_id,
                    entity_type="journal", entity_id=journal_id,
                    action="JOURNAL_PDF_LANGUAGE_UPDATED",
                    before={"pdf_locale": j.pdf_locale}, after={"pdf_locale": pdf_locale},
                )
            j.pdf_locale = pdf_locale

        if title is not None and not j.lock_header:
            j.title = title
        if notes is not None and not j.lock_footer:
            j.notes = notes

        if lock_header is not None:
            j.lock_header = lock_header
        if lock_table is not None:
            j.lock_table = lock_table
        if lock_footer is not None:
            j.lock_footer = lock_footer

        uow.journals.save(j)

    @staticmethod
    def refresh_snapshot(
        uow,
        *,
        company_id: uuid.UUID,
        journal_id: uuid.UUID,
    ) -> None:
        JournalUseCases.refresh_snapshot(
            uow,
            company_id=company_id,
            journal_id=journal_id,
        )

    @staticmethod
    def mark_ready(
        uow,
        *,
        company_id: uuid.UUID,
        journal_id: uuid.UUID,
    ) -> JournalMarkReadyResponse:
        journal = uow.journals.get(
            company_id=company_id,
            journal_id=journal_id,
        )
        if journal is None:
            raise NotFound("Journal not found")
        JournalSubmissionPolicy.evaluate(uow, journal=journal).require()
        token = JournalUseCases.mark_ready(
            uow,
            company_id=company_id,
            journal_id=journal_id,
        )
        return JournalMarkReadyResponse(
            public_token=token,
            public_url=f"/api/v1/public/journals/{token}",
            signing_url=(
                f"{settings.PUBLIC_APP_BASE_URL.rstrip('/')}/acceptance/{token}"
            ),
        )

    @staticmethod
    def export_pdf(
        uow,
        *,
        company_id: uuid.UUID,
        journal_id: uuid.UUID,
    ) -> JournalExportPdfResponse:
        file = JournalUseCases.export_pdf(
            uow,
            company_id=company_id,
            journal_id=journal_id,
        )
        return JournalExportPdfResponse(
            file_path=file.file_path,
            size_bytes=file.size_bytes,
        )
