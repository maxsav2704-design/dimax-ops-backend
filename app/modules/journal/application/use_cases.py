from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.shared.domain.errors import Conflict, Forbidden, NotFound, ValidationError
from app.modules.journal.domain.enums import JournalStatus
from app.modules.journal.infrastructure.models import (
    JournalAddonItemORM,
    JournalDoorItemORM,
    JournalFileORM,
    JournalORM,
    JournalSignatureORM,
)
from app.modules.doors.domain.enums import DoorStatus
from app.integrations.storage.storage_service import StorageService


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class JournalUseCases:
    @staticmethod
    def create_draft(
        uow,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID,
        title: str | None = None,
        installer_id: uuid.UUID | None = None,
    ) -> JournalORM:
        project = uow.projects.get(company_id=company_id, project_id=project_id)
        if not project:
            raise NotFound(
                "Project not found", details={"project_id": str(project_id)}
            )

        j = JournalORM(
            company_id=company_id,
            project_id=project_id,
            installer_id=installer_id,
            status=JournalStatus.DRAFT,
            title=title or f"Journal - {project.name}",
            lock_header=False,
            lock_table=False,
            lock_footer=False,
            snapshot_version=1,
        )
        uow.journals.save(j)
        uow.session.flush()

        JournalUseCases.refresh_snapshot(
            uow, company_id=company_id, journal_id=j.id
        )

        return j

    @staticmethod
    def refresh_snapshot(
        uow,
        *,
        company_id: uuid.UUID,
        journal_id: uuid.UUID,
    ) -> None:
        j = uow.journals.get(company_id=company_id, journal_id=journal_id)
        if not j:
            raise NotFound(
                "Journal not found", details={"journal_id": str(journal_id)}
            )

        if j.status != JournalStatus.DRAFT:
            raise Conflict(
                "Snapshot can be refreshed only in DRAFT",
                details={"status": j.status.value},
            )

        uow.journals.delete_items(company_id=company_id, journal_id=journal_id)
        uow.journals.delete_addon_items(
            company_id=company_id, journal_id=journal_id
        )

        if j.installer_id is None:
            doors = uow.doors.list_by_project(
                company_id=company_id, project_id=j.project_id
            )
            addon_facts = uow.addon_facts.list_by_project(
                company_id=company_id, project_id=j.project_id
            )
        else:
            doors = uow.doors.list_by_project_for_installer(
                company_id=company_id,
                project_id=j.project_id,
                installer_id=j.installer_id,
            )
            addon_facts = uow.addon_facts.list_by_project_for_installer(
                company_id=company_id,
                project_id=j.project_id,
                installer_id=j.installer_id,
            )
        installed = [d for d in doors if d.status == DoorStatus.INSTALLED]

        items: list[JournalDoorItemORM] = []
        for d in installed:
            items.append(
                JournalDoorItemORM(
                    company_id=company_id,
                    journal_id=journal_id,
                    door_id=d.id,
                    unit_label=d.unit_label,
                    door_type_id=d.door_type_id,
                    installed_at=d.installed_at,
                    extra=None,
                )
            )

        uow.journals.add_items(items)
        addon_types = {
            row.id: row
            for row in uow.addon_types.list_active(company_id=company_id)
        }
        addon_items: list[JournalAddonItemORM] = []
        for fact in addon_facts:
            addon_type = addon_types.get(fact.addon_type_id)
            addon_items.append(
                JournalAddonItemORM(
                    company_id=company_id,
                    journal_id=journal_id,
                    addon_fact_id=fact.id,
                    addon_type_id=fact.addon_type_id,
                    addon_name=(
                        addon_type.name if addon_type else "Additional work"
                    ),
                    unit=addon_type.unit if addon_type else "unit",
                    qty_done=fact.qty_done,
                    done_at=fact.done_at,
                    comment=fact.comment,
                )
            )
        uow.journals.add_addon_items(addon_items)
        j.snapshot_version += 1
        uow.journals.save(j)
        uow.session.flush()

    @staticmethod
    def mark_ready(
        uow,
        *,
        company_id: uuid.UUID,
        journal_id: uuid.UUID,
    ) -> str:
        j = uow.journals.get(company_id=company_id, journal_id=journal_id)
        if not j:
            raise NotFound(
                "Journal not found", details={"journal_id": str(journal_id)}
            )

        if j.status != JournalStatus.DRAFT:
            raise Conflict(
                "Only DRAFT journal can be marked ready",
                details={"status": j.status.value},
            )

        token = uuid.uuid4().hex
        j.public_token = token
        j.public_token_expires_at = utcnow() + timedelta(
            seconds=int(settings.JOURNAL_PUBLIC_TOKEN_TTL_SEC)
        )
        j.status = JournalStatus.ACTIVE
        uow.journals.save(j)
        return token

    @staticmethod
    def public_get(
        uow,
        *,
        token: str,
        for_update: bool = False,
    ) -> JournalORM:
        j = uow.journals.get_by_token(token=token, for_update=for_update)
        if not j:
            raise NotFound("Journal link not found")
        if j.status != JournalStatus.ACTIVE:
            raise Forbidden("Journal is not active")
        return j

    @staticmethod
    def public_sign(
        uow,
        *,
        token: str,
        signer_name: str,
        signature_payload: dict,
        ip: str | None,
        user_agent: str | None,
    ) -> JournalORM:
        j = JournalUseCases.public_get(uow, token=token, for_update=True)

        if j.signed_at is not None:
            raise Conflict("Journal already signed")

        if not signer_name or len(signer_name.strip()) < 2:
            raise ValidationError("signer_name is required")

        if not isinstance(signature_payload, dict) or not signature_payload:
            raise ValidationError("signature_payload is required")

        uow.journals.add_signature(
            JournalSignatureORM(
                company_id=j.company_id,
                journal_id=j.id,
                signer_name=signer_name.strip(),
                signature_payload=signature_payload,
                ip=ip,
                user_agent=user_agent,
            )
        )

        j.signed_at = utcnow()
        j.signer_name = signer_name.strip()
        j.status = JournalStatus.ARCHIVED
        uow.journals.save(j)
        uow.session.flush()
        return j

    @staticmethod
    def export_pdf(
        uow,
        *,
        company_id: uuid.UUID,
        journal_id: uuid.UUID,
    ) -> JournalFileORM:
        j = uow.journals.get(company_id=company_id, journal_id=journal_id)
        if not j:
            raise NotFound(
                "Journal not found", details={"journal_id": str(journal_id)}
            )

        project = uow.projects.get(company_id=company_id, project_id=j.project_id)
        if not project:
            raise NotFound("Project not found")

        items = (
            uow.session.query(JournalDoorItemORM)
            .filter(
                JournalDoorItemORM.company_id == company_id,
                JournalDoorItemORM.journal_id == journal_id,
            )
            .order_by(JournalDoorItemORM.unit_label.asc())
            .all()
        )
        addon_items = uow.journals.list_addon_items(
            company_id=company_id,
            journal_id=journal_id,
        )
        door_types = {
            row.id: row.name
            for row in uow.door_types.list_active(company_id=company_id)
        }
        signature = uow.journals.get_signature(
            company_id=company_id,
            journal_id=journal_id,
        )

        from app.integrations.pdf.generator import PdfGenerator

        pdf_bytes = PdfGenerator.journal_pdf(
            journal={
                "id": str(j.id),
                "title": j.title,
                "project_name": project.name,
                "project_address": project.address,
                "developer_company": project.developer_company,
                "contact_name": project.contact_name,
                "signer_name": j.signer_name,
                "signed_at": (
                    j.signed_at.isoformat() if j.signed_at else None
                ),
                "status": j.status.value,
                "snapshot_version": j.snapshot_version,
            },
            items=[
                {
                    "unit_label": it.unit_label,
                    "door_type_id": str(it.door_type_id),
                    "door_type_name": door_types.get(
                        it.door_type_id, str(it.door_type_id)
                    ),
                    "installed_at": (
                        it.installed_at.isoformat() if it.installed_at else None
                    ),
                }
                for it in items
            ],
            addon_items=[
                {
                    "name": item.addon_name,
                    "quantity": str(item.qty_done),
                    "unit": item.unit,
                    "done_at": item.done_at.isoformat(),
                    "comment": item.comment,
                }
                for item in addon_items
            ],
            signature_payload=(
                signature.signature_payload if signature is not None else None
            ),
        )

        object_key = (
            f"journals/{company_id}/{journal_id}/journal_{journal_id}.pdf"
        )
        StorageService.put_pdf(object_key=object_key, content=pdf_bytes)

        file = JournalFileORM(
            company_id=company_id,
            journal_id=journal_id,
            kind="PDF",
            file_path=object_key,
            mime_type="application/pdf",
            size_bytes=len(pdf_bytes),
            storage_provider="MINIO",
            bucket=settings.MINIO_BUCKET,
        )
        uow.journals.upsert_file(file)
        return file
