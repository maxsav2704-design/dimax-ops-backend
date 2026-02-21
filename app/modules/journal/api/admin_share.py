from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.v1.deps import CurrentUser, get_uow, require_admin
from app.modules.journal.application.admin_files_service import (
    JournalAdminFilesService,
)
from app.modules.journal.api.share_schemas import SharePdfBody, SharePdfResponse


router = APIRouter(prefix="/admin/journals", tags=["Admin / Journal"])


@router.post("/{journal_id}/pdf/share", response_model=SharePdfResponse)
def share_pdf(
    journal_id: UUID,
    body: SharePdfBody,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
) -> SharePdfResponse:
    with uow:
        return JournalAdminFilesService.share_pdf(
            uow,
            company_id=user.company_id,
            journal_id=journal_id,
            ttl_sec=body.ttl_sec,
            uses=body.uses,
            audience=body.audience,
        )
