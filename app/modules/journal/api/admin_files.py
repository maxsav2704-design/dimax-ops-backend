from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.api.v1.deps import CurrentUser, get_uow, require_admin
from app.modules.journal.application.admin_files_service import (
    JournalAdminFilesService,
)


router = APIRouter(prefix="/admin/journals", tags=["Admin / Journal"])


@router.get(
    "/{journal_id}/pdf",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "Journal PDF stream",
            "content": {
                "application/pdf": {
                    "schema": {"type": "string", "format": "binary"}
                }
            },
        }
    },
)
def download_journal_pdf(
    journal_id: UUID,
    request: Request,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")

    with uow:
        result = JournalAdminFilesService.prepare_pdf_download(
            uow,
            company_id=user.company_id,
            journal_id=journal_id,
            actor_user_id=user.id,
            ip=ip,
            user_agent=ua,
        )

        def gen():
            try:
                while True:
                    chunk = result.obj.read(1024 * 1024)
                    if not chunk:
                        break
                    yield chunk
            finally:
                try:
                    result.obj.close()
                except Exception:
                    pass
                try:
                    result.obj.release_conn()
                except Exception:
                    pass

        headers = {
            "Content-Disposition": (
                f'attachment; filename="{result.file_name}"'
            ),
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
        }

        return StreamingResponse(
            gen(),
            media_type=result.mime_type,
            headers=headers,
        )
