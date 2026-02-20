from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.v1.deps import CurrentUser, get_uow, require_admin
from app.modules.files.api.admin_schemas import (
    FileDownloadEventDTO,
    FileDownloadEventsResponse,
)
from app.modules.files.infrastructure.models import FileDownloadEventORM


router = APIRouter(prefix="/admin/files", tags=["Admin / Files"])


@router.get("/downloads", response_model=FileDownloadEventsResponse)
def list_downloads(
    journal_id: UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        q = uow.session.query(FileDownloadEventORM).filter(
            FileDownloadEventORM.company_id == user.company_id
        )
        if journal_id is not None:
            q = q.filter(
                FileDownloadEventORM.correlation_id == journal_id
            )
        rows = (
            q.order_by(FileDownloadEventORM.created_at.desc())
            .limit(limit)
            .all()
        )

        return FileDownloadEventsResponse(
            items=[
                FileDownloadEventDTO(
                    created_at=r.created_at,
                    source=r.source,
                    correlation_id=r.correlation_id,
                    ip=r.ip,
                    user_agent=r.user_agent,
                    actor_user_id=r.actor_user_id,
                    file_name=r.file_name,
                )
                for r in rows
            ]
        )
