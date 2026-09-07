from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.v1.acl import get_current_installer_id
from app.api.v1.deps import CurrentUser, get_uow, require_installer
from app.modules.audit.application.service import AuditService
from app.modules.journal.api.installer_schemas import (
    InstallerJournalDetailsResponse,
    InstallerJournalListResponse,
    InstallerJournalMarkReadyResponse,
    InstallerJournalPdfLinkResponse,
    InstallerJournalPrepareBody,
)
from app.modules.journal.application.installer_service import (
    InstallerJournalService,
)


router = APIRouter(prefix="/installer/journals", tags=["Installer / Journal"])


@router.get("", response_model=InstallerJournalListResponse)
def list_journals(
    user: CurrentUser = Depends(require_installer),
    installer_id: UUID = Depends(get_current_installer_id),
    uow=Depends(get_uow),
):
    with uow:
        return InstallerJournalService.list_journals(
            uow,
            company_id=user.company_id,
            installer_id=installer_id,
        )


@router.post("/prepare", response_model=InstallerJournalDetailsResponse)
def prepare_journal(
    body: InstallerJournalPrepareBody,
    user: CurrentUser = Depends(require_installer),
    installer_id: UUID = Depends(get_current_installer_id),
    uow=Depends(get_uow),
):
    with uow:
        result = InstallerJournalService.prepare(
            uow,
            company_id=user.company_id,
            installer_id=installer_id,
            project_id=body.project_id,
        )
        AuditService.add(
            uow,
            company_id=user.company_id,
            actor_user_id=user.id,
            entity_type="journal",
            entity_id=result["id"],
            action="INSTALLER_JOURNAL_PREPARED",
            after={
                "project_id": str(body.project_id),
                "completed_doors": result["completed_doors"],
                "completed_addons": result["completed_addons"],
            },
        )
        return result


@router.get("/{journal_id}", response_model=InstallerJournalDetailsResponse)
def get_journal(
    journal_id: UUID,
    user: CurrentUser = Depends(require_installer),
    installer_id: UUID = Depends(get_current_installer_id),
    uow=Depends(get_uow),
):
    with uow:
        return InstallerJournalService.get_journal(
            uow,
            company_id=user.company_id,
            installer_id=installer_id,
            journal_id=journal_id,
        )


@router.post("/{journal_id}/refresh", response_model=InstallerJournalDetailsResponse)
def refresh_journal(
    journal_id: UUID,
    user: CurrentUser = Depends(require_installer),
    installer_id: UUID = Depends(get_current_installer_id),
    uow=Depends(get_uow),
):
    with uow:
        return InstallerJournalService.refresh(
            uow,
            company_id=user.company_id,
            installer_id=installer_id,
            journal_id=journal_id,
        )


@router.post(
    "/{journal_id}/mark-ready",
    response_model=InstallerJournalMarkReadyResponse,
)
def mark_ready(
    journal_id: UUID,
    user: CurrentUser = Depends(require_installer),
    installer_id: UUID = Depends(get_current_installer_id),
    uow=Depends(get_uow),
):
    with uow:
        result = InstallerJournalService.mark_ready(
            uow,
            company_id=user.company_id,
            installer_id=installer_id,
            journal_id=journal_id,
        )
        AuditService.add(
            uow,
            company_id=user.company_id,
            actor_user_id=user.id,
            entity_type="journal",
            entity_id=journal_id,
            action="INSTALLER_JOURNAL_SENT_FOR_SIGNATURE",
            after={"expires_at": result["public_token_expires_at"].isoformat()},
        )
        return result


@router.post(
    "/{journal_id}/pdf-link",
    response_model=InstallerJournalPdfLinkResponse,
)
def create_pdf_link(
    journal_id: UUID,
    user: CurrentUser = Depends(require_installer),
    installer_id: UUID = Depends(get_current_installer_id),
    uow=Depends(get_uow),
):
    with uow:
        return InstallerJournalService.share_pdf(
            uow,
            company_id=user.company_id,
            installer_id=installer_id,
            journal_id=journal_id,
        )
