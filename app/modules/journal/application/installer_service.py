from __future__ import annotations

import uuid
from urllib.parse import quote

from app.core.config import settings
from app.modules.files.application.service import FileTokenService
from app.modules.journal.application.submission_policy import (
    JournalSubmissionPolicy,
)
from app.modules.journal.application.use_cases import JournalUseCases
from app.modules.journal.domain.enums import JournalStatus
from app.shared.domain.errors import Conflict, Forbidden, NotFound


def _value(value) -> str:
    return value.value if hasattr(value, "value") else str(value)


class InstallerJournalService:
    @staticmethod
    def _assert_project_access(
        uow,
        *,
        company_id: uuid.UUID,
        installer_id: uuid.UUID,
        project_id: uuid.UUID,
    ):
        project = uow.projects.get(company_id=company_id, project_id=project_id)
        if project is None:
            raise NotFound("Project not found")
        assigned = uow.doors.list_by_project_for_installer(
            company_id=company_id,
            project_id=project_id,
            installer_id=installer_id,
        )
        if not assigned:
            raise Forbidden("Project is not assigned to this installer")
        return project, assigned

    @staticmethod
    def _get_owned(
        uow,
        *,
        company_id: uuid.UUID,
        installer_id: uuid.UUID,
        journal_id: uuid.UUID,
    ):
        journal = uow.journals.get_for_installer(
            company_id=company_id,
            installer_id=installer_id,
            journal_id=journal_id,
        )
        if journal is None:
            raise NotFound("Journal not found")
        InstallerJournalService._assert_project_access(
            uow,
            company_id=company_id,
            installer_id=installer_id,
            project_id=journal.project_id,
        )
        return journal

    @staticmethod
    def _details(uow, *, journal) -> dict:
        project = uow.projects.get(
            company_id=journal.company_id,
            project_id=journal.project_id,
        )
        door_items = uow.journals.list_items(
            company_id=journal.company_id,
            journal_id=journal.id,
        )
        addon_items = uow.journals.list_addon_items(
            company_id=journal.company_id,
            journal_id=journal.id,
        )
        door_types = {
            row.id: row.name
            for row in uow.door_types.list_active(company_id=journal.company_id)
        }
        readiness = JournalSubmissionPolicy.evaluate(
            uow,
            journal=journal,
            project=project,
            door_items=door_items,
            addon_items=addon_items,
        )
        signing_url = None
        if journal.public_token:
            signing_url = (
                f"{settings.PUBLIC_APP_BASE_URL.rstrip('/')}/acceptance/"
                f"{journal.public_token}"
            )
        return {
            "id": journal.id,
            "project_id": journal.project_id,
            "project_name": project.name if project else "",
            "project_address": project.address if project else None,
            "developer_company": project.developer_company if project else None,
            "developer_email": readiness.developer_email,
            "status": _value(journal.status),
            "completed_doors": len(door_items),
            "completed_addons": len(addon_items),
            "signed_at": journal.signed_at,
            "signer_name": journal.signer_name,
            "email_delivery_status": _value(journal.email_delivery_status),
            "email_last_error": journal.email_last_error,
            "can_submit": journal.status == JournalStatus.DRAFT
            and readiness.can_submit,
            "title": journal.title,
            "snapshot_version": journal.snapshot_version,
            "public_token_expires_at": journal.public_token_expires_at,
            "signing_url": signing_url,
            "doors": [
                {
                    "unit_label": item.unit_label,
                    "door_type_name": door_types.get(
                        item.door_type_id, str(item.door_type_id)
                    ),
                    "installed_at": item.installed_at,
                }
                for item in door_items
            ],
            "addon_items": [
                {
                    "name": item.addon_name,
                    "quantity": str(item.qty_done),
                    "unit": item.unit,
                    "done_at": item.done_at,
                    "comment": item.comment,
                }
                for item in addon_items
            ],
        }

    @staticmethod
    def list_journals(
        uow, *, company_id: uuid.UUID, installer_id: uuid.UUID
    ) -> dict:
        assigned_project_ids = set(
            uow.doors.list_project_ids_for_installer(
                company_id=company_id,
                installer_id=installer_id,
            )
        )
        journals = uow.journals.list_for_installer(
            company_id=company_id,
            installer_id=installer_id,
        )
        return {
            "items": [
                InstallerJournalService._details(uow, journal=journal)
                for journal in journals
                if journal.project_id in assigned_project_ids
            ]
        }

    @staticmethod
    def prepare(
        uow,
        *,
        company_id: uuid.UUID,
        installer_id: uuid.UUID,
        project_id: uuid.UUID,
    ) -> dict:
        project, _assigned = InstallerJournalService._assert_project_access(
            uow,
            company_id=company_id,
            installer_id=installer_id,
            project_id=project_id,
        )
        journal = uow.journals.get_draft_for_installer_project(
            company_id=company_id,
            installer_id=installer_id,
            project_id=project_id,
        )
        if journal is None:
            journal = JournalUseCases.create_draft(
                uow,
                company_id=company_id,
                project_id=project_id,
                installer_id=installer_id,
                title=f"Work acceptance - {project.name}",
            )
        else:
            JournalUseCases.refresh_snapshot(
                uow,
                company_id=company_id,
                journal_id=journal.id,
            )
        return InstallerJournalService._details(uow, journal=journal)

    @staticmethod
    def get_journal(
        uow,
        *,
        company_id: uuid.UUID,
        installer_id: uuid.UUID,
        journal_id: uuid.UUID,
    ) -> dict:
        journal = InstallerJournalService._get_owned(
            uow,
            company_id=company_id,
            installer_id=installer_id,
            journal_id=journal_id,
        )
        return InstallerJournalService._details(uow, journal=journal)

    @staticmethod
    def refresh(
        uow,
        *,
        company_id: uuid.UUID,
        installer_id: uuid.UUID,
        journal_id: uuid.UUID,
    ) -> dict:
        journal = InstallerJournalService._get_owned(
            uow,
            company_id=company_id,
            installer_id=installer_id,
            journal_id=journal_id,
        )
        JournalUseCases.refresh_snapshot(
            uow,
            company_id=company_id,
            journal_id=journal.id,
        )
        return InstallerJournalService._details(uow, journal=journal)

    @staticmethod
    def mark_ready(
        uow,
        *,
        company_id: uuid.UUID,
        installer_id: uuid.UUID,
        journal_id: uuid.UUID,
    ) -> dict:
        journal = InstallerJournalService._get_owned(
            uow,
            company_id=company_id,
            installer_id=installer_id,
            journal_id=journal_id,
        )
        JournalSubmissionPolicy.evaluate(uow, journal=journal).require()
        token = JournalUseCases.mark_ready(
            uow,
            company_id=company_id,
            journal_id=journal.id,
        )
        if journal.public_token_expires_at is None:
            raise Conflict("Journal signing link has no expiration")
        return {
            "signing_url": (
                f"{settings.PUBLIC_APP_BASE_URL.rstrip('/')}/acceptance/{token}"
            ),
            "public_token_expires_at": journal.public_token_expires_at,
        }

    @staticmethod
    def share_pdf(
        uow,
        *,
        company_id: uuid.UUID,
        installer_id: uuid.UUID,
        journal_id: uuid.UUID,
    ) -> dict:
        journal = InstallerJournalService._get_owned(
            uow,
            company_id=company_id,
            installer_id=installer_id,
            journal_id=journal_id,
        )
        if journal.status != JournalStatus.ARCHIVED:
            raise Conflict("Signed PDF is available only after acceptance")
        file_row = uow.journals.get_file(
            company_id=company_id,
            journal_id=journal.id,
            kind="PDF",
        )
        if file_row is None:
            file_row = JournalUseCases.export_pdf(
                uow,
                company_id=company_id,
                journal_id=journal.id,
            )
        ttl_sec = 3600
        uses = 3
        audience = f"installer:{installer_id}"
        token = FileTokenService.create_token_for_object(
            uow,
            company_id=company_id,
            bucket=file_row.bucket,
            object_key=file_row.file_path,
            mime_type=file_row.mime_type,
            file_name=f"dimax_acceptance_{str(journal.id)[:8]}.pdf",
            ttl_sec=ttl_sec,
            uses=uses,
            audience=audience,
        )
        return {
            "url": (
                f"{settings.PUBLIC_BASE_URL.rstrip('/')}/api/v1/public/files/"
                f"{token}?aud={quote(audience, safe='')}"
            ),
            "ttl_sec": ttl_sec,
            "uses": uses,
        }
