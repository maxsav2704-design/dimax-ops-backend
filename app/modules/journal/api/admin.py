from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.v1.deps import CurrentUser, get_uow, require_admin
from app.modules.journal.api.schemas import (
    JournalCreateResponse,
    JournalCreateBody,
    JournalExportPdfResponse,
    JournalListResponse,
    JournalMarkReadyResponse,
    JournalUpdateBody,
    OkResponse,
    JournalDetailsResponse,
)
from app.modules.journal.application.admin_service import JournalAdminService


router = APIRouter(prefix="/admin/journals", tags=["Admin / Journal"])


@router.get("", response_model=JournalListResponse)
def list_journals(
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return JournalAdminService.list_journals(
            uow,
            company_id=user.company_id,
            status=status,
            limit=limit,
            offset=offset,
        )


@router.post("", response_model=JournalCreateResponse)
def create_draft(
    body: JournalCreateBody,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return JournalAdminService.create_draft(
            uow,
            company_id=user.company_id,
            project_id=body.project_id,
            title=body.title,
        )


@router.get("/{journal_id}", response_model=JournalDetailsResponse)
def get_journal(
    journal_id: UUID,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return JournalAdminService.get_journal(
            uow,
            company_id=user.company_id, journal_id=journal_id
        )


@router.patch("/{journal_id}", response_model=OkResponse)
def update_journal(
    journal_id: UUID,
    body: JournalUpdateBody,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        JournalAdminService.update_journal(
            uow,
            company_id=user.company_id,
            journal_id=journal_id,
            title=body.title,
            notes=body.notes,
            lock_header=body.lock_header,
            lock_table=body.lock_table,
            lock_footer=body.lock_footer,
        )

    return OkResponse()


@router.post("/{journal_id}/refresh-snapshot", response_model=OkResponse)
def refresh_snapshot(
    journal_id: UUID,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        JournalAdminService.refresh_snapshot(
            uow,
            company_id=user.company_id,
            journal_id=journal_id,
        )
    return OkResponse()


@router.post("/{journal_id}/mark-ready", response_model=JournalMarkReadyResponse)
def mark_ready(
    journal_id: UUID,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return JournalAdminService.mark_ready(
            uow,
            company_id=user.company_id,
            journal_id=journal_id,
        )


@router.post("/{journal_id}/export-pdf", response_model=JournalExportPdfResponse)
def export_pdf(
    journal_id: UUID,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return JournalAdminService.export_pdf(
            uow,
            company_id=user.company_id,
            journal_id=journal_id,
        )
