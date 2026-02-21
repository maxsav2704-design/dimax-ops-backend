from __future__ import annotations

import uuid

from app.modules.journal.api.schemas import (
    JournalCreateResponse,
    JournalExportPdfResponse,
    JournalMarkReadyResponse,
)
from app.modules.journal.application.use_cases import JournalUseCases
from app.shared.domain.errors import Conflict, NotFound


def _status_value(s) -> str:
    return s.value if hasattr(s, "value") else str(s)


class JournalAdminService:
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
    ) -> JournalCreateResponse:
        j = JournalUseCases.create_draft(
            uow,
            company_id=company_id,
            project_id=project_id,
            title=title,
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
            "public_token": j.public_token,
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
    ) -> None:
        j = uow.journals.get(company_id=company_id, journal_id=journal_id)
        if not j:
            raise NotFound("Journal not found")

        if _status_value(j.status) != "DRAFT":
            raise Conflict("Only DRAFT journal can be edited")

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
        token = JournalUseCases.mark_ready(
            uow,
            company_id=company_id,
            journal_id=journal_id,
        )
        return JournalMarkReadyResponse(
            public_token=token,
            public_url=f"/api/v1/public/journals/{token}",
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
