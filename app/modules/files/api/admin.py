from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.v1.deps import CurrentUser, get_uow, require_admin
from app.modules.files.api.admin_schemas import FileDownloadEventsResponse
from app.modules.files.application.api_service import FilesAdminService


router = APIRouter(prefix="/admin/files", tags=["Admin / Files"])


@router.get("/downloads", response_model=FileDownloadEventsResponse)
def list_downloads(
    journal_id: UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return FilesAdminService.list_downloads(
            uow,
            company_id=user.company_id,
            journal_id=journal_id,
            limit=limit,
        )
