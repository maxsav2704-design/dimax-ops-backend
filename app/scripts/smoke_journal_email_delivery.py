from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone

from app.core.config import settings
from app.integrations.pdf.generator import PdfGenerator
from app.integrations.storage.minio_client import get_minio
from app.integrations.storage.storage_service import StorageService
from app.modules.identity.infrastructure.models import CompanyORM
from app.modules.outbox.domain.enums import OutboxChannel, OutboxStatus
from app.modules.outbox.infrastructure.models import OutboxMessageORM
from app.shared.infrastructure.db.session import SessionLocal
from app.workers.outbox_worker import run_once


def main() -> None:
    app_env = os.getenv("APP_ENV", "dev").strip().lower()
    if app_env not in {"dev", "development", "local", "test"}:
        raise RuntimeError("Journal email smoke is restricted to non-production environments")

    marker = uuid.uuid4().hex[:10]
    subject = f"DIMAX journal delivery smoke {marker}"
    attachment_name = f"dimax-journal-{marker}.pdf"
    object_key = f"smoke/journal-email/{marker}.pdf"
    pdf_bytes = PdfGenerator.journal_pdf(
        journal={
            "id": marker,
            "title": "Completed installation works",
            "project_name": "DIMAX QA Object",
            "project_address": "1 Test Street",
            "developer_company": "Developer QA",
            "contact_name": "Acceptance Manager",
            "status": "SIGNED",
            "signer_name": "Developer Representative",
            "signed_at": datetime.now(timezone.utc).isoformat(),
        },
        items=[
            {
                "unit_label": "A-101",
                "door_type_name": "Entrance door",
                "installed_at": datetime.now(timezone.utc).isoformat(),
            }
        ],
        addon_items=[],
        signature_payload={
            "viewport": {"width": 200, "height": 80},
            "strokes": [[{"x": 20, "y": 50}, {"x": 170, "y": 25}]],
        },
    )
    StorageService.put_pdf(object_key=object_key, content=pdf_bytes)

    session = SessionLocal()
    try:
        company = session.query(CompanyORM).order_by(CompanyORM.created_at.asc()).first()
        if company is None:
            raise RuntimeError("No company exists; run the workspace seed first")
        message = OutboxMessageORM(
            company_id=company.id,
            channel=OutboxChannel.EMAIL,
            status=OutboxStatus.PENDING,
            correlation_id=None,
            payload={
                "to_email": "developer.smoke@example.test",
                "cc_emails": ["admin.smoke@example.test"],
                "subject": subject,
                "body_text": "Signed DIMAX journal PDF delivery smoke.",
                "object_key": object_key,
                "attachment_name": attachment_name,
            },
            scheduled_at=datetime.now(timezone.utc),
        )
        session.add(message)
        session.commit()
        outbox_id = message.id
    finally:
        session.close()

    processed = run_once(limit=20)

    session = SessionLocal()
    try:
        stored = session.get(OutboxMessageORM, outbox_id)
        if stored is None or stored.status != OutboxStatus.SENT:
            status = stored.status.value if stored is not None else "MISSING"
            error = stored.last_error if stored is not None else None
            raise RuntimeError(f"Email smoke failed: status={status}, error={error}")
        session.delete(stored)
        session.commit()
    finally:
        session.close()

    get_minio().remove_object(settings.MINIO_BUCKET, object_key)
    print(
        json.dumps(
            {
                "status": "ok",
                "subject": subject,
                "to": "developer.smoke@example.test",
                "cc": ["admin.smoke@example.test"],
                "attachment_name": attachment_name,
                "pdf_bytes": len(pdf_bytes),
                "processed": processed,
            }
        )
    )


if __name__ == "__main__":
    main()
