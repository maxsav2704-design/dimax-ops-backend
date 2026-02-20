from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.v1.deps import CurrentUser, get_uow, require_admin
from app.modules.journal.api.schemas import (
    JournalCreateBody,
    JournalDetailsResponse,
    JournalListItem,
    JournalListResponse,
    JournalUpdateBody,
    OkResponse,
)
from app.modules.journal.application.use_cases import JournalUseCases
from app.shared.domain.errors import Conflict, NotFound


router = APIRouter(prefix="/admin/journals", tags=["Admin / Journal"])


def _status_value(s) -> str:
    return s.value if hasattr(s, "value") else str(s)


def _delivery_status_value(s) -> str:
    return s.value if hasattr(s, "value") else str(s)


@router.get("", response_model=JournalListResponse)
def list_journals(
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        items = uow.journals.list(
            company_id=user.company_id,
            status=status,
            limit=limit,
            offset=offset,
        )
        return JournalListResponse(
            items=[
                JournalListItem(
                    id=j.id,
                    project_id=j.project_id,
                    status=_status_value(j.status),
                    title=j.title,
                    signed_at=(
                        j.signed_at.isoformat() if j.signed_at else None
                    ),
                )
                for j in items
            ]
        )


@router.post("", response_model=dict)
def create_draft(
    body: JournalCreateBody,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        j = JournalUseCases.create_draft(
            uow,
            company_id=user.company_id,
            project_id=body.project_id,
            title=body.title,
        )
        return {"id": str(j.id)}


@router.get("/{journal_id}", response_model=JournalDetailsResponse)
def get_journal(
    journal_id: UUID,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        j = uow.journals.get(
            company_id=user.company_id, journal_id=journal_id
        )
        if not j:
            raise NotFound("Journal not found")

        return JournalDetailsResponse(
            id=j.id,
            project_id=j.project_id,
            status=_status_value(j.status),
            title=j.title,
            notes=j.notes,
            public_token=j.public_token,
            lock_header=j.lock_header,
            lock_table=j.lock_table,
            lock_footer=j.lock_footer,
            signed_at=(
                j.signed_at.isoformat() if j.signed_at else None
            ),
            signer_name=j.signer_name,
            snapshot_version=j.snapshot_version,
            email_delivery_status=_delivery_status_value(j.email_delivery_status),
            whatsapp_delivery_status=_delivery_status_value(
                j.whatsapp_delivery_status
            ),
            email_last_sent_at=j.email_last_sent_at,
            whatsapp_last_sent_at=j.whatsapp_last_sent_at,
            whatsapp_delivered_at=j.whatsapp_delivered_at,
            email_last_error=j.email_last_error,
            whatsapp_last_error=j.whatsapp_last_error,
        )


@router.patch("/{journal_id}", response_model=OkResponse)
def update_journal(
    journal_id: UUID,
    body: JournalUpdateBody,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        j = uow.journals.get(
            company_id=user.company_id, journal_id=journal_id
        )
        if not j:
            raise NotFound("Journal not found")

        if _status_value(j.status) != "DRAFT":
            raise Conflict("Only DRAFT journal can be edited")

        if body.title is not None and not j.lock_header:
            j.title = body.title
        if body.notes is not None and not j.lock_footer:
            j.notes = body.notes

        if body.lock_header is not None:
            j.lock_header = body.lock_header
        if body.lock_table is not None:
            j.lock_table = body.lock_table
        if body.lock_footer is not None:
            j.lock_footer = body.lock_footer

        uow.journals.save(j)

    return OkResponse()


@router.post("/{journal_id}/refresh-snapshot", response_model=OkResponse)
def refresh_snapshot(
    journal_id: UUID,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        JournalUseCases.refresh_snapshot(
            uow,
            company_id=user.company_id,
            journal_id=journal_id,
        )
    return OkResponse()


@router.post("/{journal_id}/mark-ready", response_model=dict)
def mark_ready(
    journal_id: UUID,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        token = JournalUseCases.mark_ready(
            uow,
            company_id=user.company_id,
            journal_id=journal_id,
        )
        return {
            "public_token": token,
            "public_url": f"/api/v1/public/journals/{token}",
        }


@router.post("/{journal_id}/export-pdf", response_model=dict)
def export_pdf(
    journal_id: UUID,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        file = JournalUseCases.export_pdf(
            uow,
            company_id=user.company_id,
            journal_id=journal_id,
        )
        return {"file_path": file.file_path, "size_bytes": file.size_bytes}
