from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.api.v1.deps import CurrentUser, get_uow, require_admin
from app.integrations.storage.storage_service import StorageService
from app.modules.files.infrastructure.models import FileDownloadEventORM
from app.shared.domain.errors import NotFound


router = APIRouter(prefix="/admin/journals", tags=["Admin / Journal"])


def _ensure_pdf(uow, *, company_id: UUID, journal_id: UUID):
    from app.modules.journal.application.use_cases import JournalUseCases

    return JournalUseCases.export_pdf(
        uow, company_id=company_id, journal_id=journal_id
    )


@router.get("/{journal_id}/pdf")
def download_journal_pdf(
    journal_id: UUID,
    request: Request,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")

    with uow:
        j = uow.journals.get(company_id=user.company_id, journal_id=journal_id)
        if not j:
            raise NotFound(
                "Journal not found", details={"journal_id": str(journal_id)}
            )

        f = uow.journals.get_file(
            company_id=user.company_id,
            journal_id=journal_id,
            kind="PDF",
        )
        if not f:
            f = _ensure_pdf(
                uow,
                company_id=user.company_id,
                journal_id=journal_id,
            )

        obj = StorageService.get_object_stream(
            bucket=f.bucket, object_key=f.file_path
        )

        uow.file_download_events.add(
            FileDownloadEventORM(
                company_id=user.company_id,
                source="ADMIN",
                token=None,
                object_key=f.file_path,
                bucket=f.bucket,
                mime_type=f.mime_type,
                file_name=f"journal_{journal_id}.pdf",
                ip=ip,
                user_agent=ua,
                actor_user_id=user.id,
                correlation_id=journal_id,
            )
        )

        def gen():
            try:
                while True:
                    chunk = obj.read(1024 * 1024)
                    if not chunk:
                        break
                    yield chunk
            finally:
                try:
                    obj.close()
                except Exception:
                    pass
                try:
                    obj.release_conn()
                except Exception:
                    pass

        headers = {
            "Content-Disposition": f'attachment; filename="journal_{journal_id}.pdf"',
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
        }

        return StreamingResponse(
            gen(), media_type=f.mime_type, headers=headers
        )
