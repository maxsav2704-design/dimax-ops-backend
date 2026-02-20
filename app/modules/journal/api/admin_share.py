from __future__ import annotations

from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.v1.deps import CurrentUser, get_uow, require_admin
from app.core.config import settings
from app.modules.files.application.service import FileTokenService
from app.modules.journal.api.share_schemas import SharePdfBody
from app.shared.domain.errors import NotFound


router = APIRouter(prefix="/admin/journals", tags=["Admin / Journal"])


@router.post("/{journal_id}/pdf/share")
def share_pdf(
    journal_id: UUID,
    body: SharePdfBody,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
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
            from app.modules.journal.application.use_cases import (
                JournalUseCases,
            )

            f = JournalUseCases.export_pdf(
                uow,
                company_id=user.company_id,
                journal_id=journal_id,
            )

        token = FileTokenService.create_token_for_object(
            uow,
            company_id=user.company_id,
            bucket=f.bucket,
            object_key=f.file_path,
            mime_type=f.mime_type,
            file_name=f"journal_{journal_id}.pdf",
            ttl_sec=body.ttl_sec,
            uses=body.uses,
            audience=body.audience,
        )

        url = f"{settings.PUBLIC_BASE_URL}/api/v1/public/files/{token}"
        if body.audience:
            url += f"?aud={quote(body.audience, safe='')}"
        return {
            "url": url,
            "ttl_sec": body.ttl_sec,
            "uses": body.uses,
        }
