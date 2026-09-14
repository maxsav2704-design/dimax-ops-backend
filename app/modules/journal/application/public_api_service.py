from __future__ import annotations

from app.modules.journal.application.use_cases import JournalUseCases
from app.modules.journal.application.snapshot import read_journal_snapshot
from app.modules.journal.application.signed_delivery_service import (
    JournalSignedDeliveryService,
)


class JournalPublicApiService:
    @staticmethod
    def public_get(uow, *, token: str) -> dict:
        journal = JournalUseCases.public_get(uow, token=token)
        return read_journal_snapshot(uow, journal=journal)

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
