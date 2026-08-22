from __future__ import annotations

from app.modules.journal.application.use_cases import JournalUseCases
from app.modules.journal.application.signed_delivery_service import (
    JournalSignedDeliveryService,
)


def _status_value(value) -> str:
    return value.value if hasattr(value, "value") else str(value)


class JournalPublicApiService:
    @staticmethod
    def public_get(uow, *, token: str) -> dict:
        journal = JournalUseCases.public_get(uow, token=token)
        items = uow.journals.list_items(
            company_id=journal.company_id,
            journal_id=journal.id,
        )
        addon_items = uow.journals.list_addon_items(
            company_id=journal.company_id,
            journal_id=journal.id,
        )
        project = uow.projects.get(
            company_id=journal.company_id,
            project_id=journal.project_id,
        )
        door_types = {
            row.id: row.name
            for row in uow.door_types.list_active(company_id=journal.company_id)
        }

        return {
            "journal": {
                "id": str(journal.id),
                "project_id": str(journal.project_id),
                "status": _status_value(journal.status),
                "title": journal.title,
                "notes": journal.notes,
                "lock_header": journal.lock_header,
                "lock_table": journal.lock_table,
                "lock_footer": journal.lock_footer,
                "signed_at": (
                    journal.signed_at.isoformat() if journal.signed_at else None
                ),
                "signer_name": journal.signer_name,
                "snapshot_version": journal.snapshot_version,
            },
            "project": {
                "name": project.name if project else "",
                "address": project.address if project else None,
                "developer_company": (
                    project.developer_company if project else None
                ),
                "contact_name": project.contact_name if project else None,
            },
            "items": [
                {
                    "unit_label": item.unit_label,
                    "door_type_id": str(item.door_type_id),
                    "door_type_name": door_types.get(
                        item.door_type_id, str(item.door_type_id)
                    ),
                    "installed_at": (
                        item.installed_at.isoformat()
                        if item.installed_at
                        else None
                    ),
                }
                for item in items
            ],
            "addon_items": [
                {
                    "name": item.addon_name,
                    "quantity": str(item.qty_done),
                    "unit": item.unit,
                    "done_at": item.done_at.isoformat(),
                    "comment": item.comment,
                }
                for item in addon_items
            ],
        }

    @staticmethod
    def public_sign(
        uow,
        *,
        token: str,
        signer_name: str,
        signature_payload: dict,
        ip: str | None,
        user_agent: str | None,
    ) -> dict:
        journal = JournalUseCases.public_sign(
            uow,
            token=token,
            signer_name=signer_name,
            signature_payload=signature_payload,
            ip=ip,
            user_agent=user_agent,
        )
        delivery = JournalSignedDeliveryService.enqueue(uow, journal=journal)
        return {
            "ok": True,
            "pdf_ready": True,
            "email_queued": delivery["queued"],
        }
