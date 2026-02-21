from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.modules.journal.domain.enums import JournalDeliveryStatus
from app.modules.journal.infrastructure.models import (
    JournalDoorItemORM,
    JournalFileORM,
    JournalORM,
    JournalSignatureORM,
)


class JournalRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(
        self, *, company_id: uuid.UUID, journal_id: uuid.UUID
    ) -> JournalORM | None:
        return (
            self.session.query(JournalORM)
            .filter(
                JournalORM.company_id == company_id,
                JournalORM.id == journal_id,
            )
            .one_or_none()
        )

    def get_by_token(self, *, token: str) -> JournalORM | None:
        return (
            self.session.query(JournalORM)
            .filter(JournalORM.public_token == token)
            .one_or_none()
        )

    def list(
        self,
        *,
        company_id: uuid.UUID,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[JournalORM]:
        q = self.session.query(JournalORM).filter(
            JournalORM.company_id == company_id
        )
        if status:
            q = q.filter(JournalORM.status == status)
        return (
            q.order_by(JournalORM.created_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )

    def save(self, journal: JournalORM) -> None:
        self.session.add(journal)

    def delete_items(
        self, *, company_id: uuid.UUID, journal_id: uuid.UUID
    ) -> None:
        self.session.query(JournalDoorItemORM).filter(
            JournalDoorItemORM.company_id == company_id,
            JournalDoorItemORM.journal_id == journal_id,
        ).delete(synchronize_session=False)

    def add_items(self, items: list[JournalDoorItemORM]) -> None:
        self.session.add_all(items)

    def list_items(
        self,
        *,
        company_id: uuid.UUID,
        journal_id: uuid.UUID,
    ) -> list[JournalDoorItemORM]:
        return (
            self.session.query(JournalDoorItemORM)
            .filter(
                JournalDoorItemORM.company_id == company_id,
                JournalDoorItemORM.journal_id == journal_id,
            )
            .order_by(JournalDoorItemORM.unit_label.asc())
            .all()
        )

    def add_signature(self, sig: JournalSignatureORM) -> None:
        self.session.add(sig)

    def upsert_file(self, file: JournalFileORM) -> None:
        self.session.query(JournalFileORM).filter(
            JournalFileORM.company_id == file.company_id,
            JournalFileORM.journal_id == file.journal_id,
            JournalFileORM.kind == file.kind,
        ).delete(synchronize_session=False)
        self.session.add(file)

    def get_file(
        self,
        *,
        company_id: uuid.UUID,
        journal_id: uuid.UUID,
        kind: str,
    ) -> JournalFileORM | None:
        return (
            self.session.query(JournalFileORM)
            .filter(
                JournalFileORM.company_id == company_id,
                JournalFileORM.journal_id == journal_id,
                JournalFileORM.kind == kind,
            )
            .one_or_none()
        )

    def set_email_status(
        self,
        *,
        company_id: uuid.UUID,
        journal_id: uuid.UUID,
        status: JournalDeliveryStatus,
        sent_at: datetime | None = None,
        error: str | None = None,
    ) -> None:
        j = (
            self.session.query(JournalORM)
            .filter(
                JournalORM.company_id == company_id,
                JournalORM.id == journal_id,
            )
            .first()
        )
        if not j:
            return
        j.email_delivery_status = status
        if sent_at is not None:
            j.email_last_sent_at = sent_at
        if error is not None:
            j.email_last_error = error[:5000]
        self.session.add(j)

    def set_whatsapp_status(
        self,
        *,
        company_id: uuid.UUID,
        journal_id: uuid.UUID,
        status: JournalDeliveryStatus,
        sent_at: datetime | None = None,
        delivered_at: datetime | None = None,
        error: str | None = None,
    ) -> None:
        j = (
            self.session.query(JournalORM)
            .filter(
                JournalORM.company_id == company_id,
                JournalORM.id == journal_id,
            )
            .first()
        )
        if not j:
            return
        j.whatsapp_delivery_status = status
        if sent_at is not None:
            j.whatsapp_last_sent_at = sent_at
        if delivered_at is not None:
            j.whatsapp_delivered_at = delivered_at
        if error is not None:
            j.whatsapp_last_error = error[:5000]
        self.session.add(j)
