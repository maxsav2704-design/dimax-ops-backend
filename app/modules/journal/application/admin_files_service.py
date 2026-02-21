from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote
from uuid import UUID

from app.core.config import settings
from app.integrations.storage.storage_service import StorageService
from app.modules.files.application.service import FileTokenService
from app.modules.files.infrastructure.models import FileDownloadEventORM
from app.shared.domain.errors import NotFound


@dataclass(frozen=True)
class JournalPdfDownloadResult:
    obj: object
    mime_type: str
    file_name: str


def _ensure_pdf(uow, *, company_id: UUID, journal_id: UUID):
    from app.modules.journal.application.use_cases import JournalUseCases

    return JournalUseCases.export_pdf(
        uow,
        company_id=company_id,
        journal_id=journal_id,
    )


class JournalAdminFilesService:
    @staticmethod
    def prepare_pdf_download(
        uow,
        *,
        company_id: UUID,
        journal_id: UUID,
        actor_user_id: UUID,
        ip: str | None,
        user_agent: str | None,
    ) -> JournalPdfDownloadResult:
        journal = uow.journals.get(company_id=company_id, journal_id=journal_id)
        if not journal:
            raise NotFound(
                "Journal not found",
                details={"journal_id": str(journal_id)},
            )

        file_row = uow.journals.get_file(
            company_id=company_id,
            journal_id=journal_id,
            kind="PDF",
        )
        if not file_row:
            file_row = _ensure_pdf(
                uow,
                company_id=company_id,
                journal_id=journal_id,
            )

        obj = StorageService.get_object_stream(
            bucket=file_row.bucket,
            object_key=file_row.file_path,
        )

        uow.file_download_events.add(
            FileDownloadEventORM(
                company_id=company_id,
                source="ADMIN",
                token=None,
                object_key=file_row.file_path,
                bucket=file_row.bucket,
                mime_type=file_row.mime_type,
                file_name=f"journal_{journal_id}.pdf",
                ip=ip,
                user_agent=user_agent,
                actor_user_id=actor_user_id,
                correlation_id=journal_id,
            )
        )

        return JournalPdfDownloadResult(
            obj=obj,
            mime_type=file_row.mime_type,
            file_name=f"journal_{journal_id}.pdf",
        )

    @staticmethod
    def share_pdf(
        uow,
        *,
        company_id: UUID,
        journal_id: UUID,
        ttl_sec: int,
        uses: int,
        audience: str | None,
    ) -> dict:
        journal = uow.journals.get(company_id=company_id, journal_id=journal_id)
        if not journal:
            raise NotFound(
                "Journal not found",
                details={"journal_id": str(journal_id)},
            )

        file_row = uow.journals.get_file(
            company_id=company_id,
            journal_id=journal_id,
            kind="PDF",
        )
        if not file_row:
            file_row = _ensure_pdf(
                uow,
                company_id=company_id,
                journal_id=journal_id,
            )

        token = FileTokenService.create_token_for_object(
            uow,
            company_id=company_id,
            bucket=file_row.bucket,
            object_key=file_row.file_path,
            mime_type=file_row.mime_type,
            file_name=f"journal_{journal_id}.pdf",
            ttl_sec=ttl_sec,
            uses=uses,
            audience=audience,
        )

        url = f"{settings.PUBLIC_BASE_URL}/api/v1/public/files/{token}"
        if audience:
            url += f"?aud={quote(audience, safe='')}"

        return {
            "url": url,
            "ttl_sec": ttl_sec,
            "uses": uses,
        }
