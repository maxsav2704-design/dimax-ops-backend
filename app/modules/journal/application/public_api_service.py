from __future__ import annotations

from app.modules.journal.application.use_cases import JournalUseCases


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
            "items": [
                {
                    "unit_label": item.unit_label,
                    "door_type_id": str(item.door_type_id),
                    "installed_at": (
                        item.installed_at.isoformat()
                        if item.installed_at
                        else None
                    ),
                }
                for item in items
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
    ) -> None:
        JournalUseCases.public_sign(
            uow,
            token=token,
            signer_name=signer_name,
            signature_payload=signature_payload,
            ip=ip,
            user_agent=user_agent,
        )
