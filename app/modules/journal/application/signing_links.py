from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote

from app.core.config import settings
from app.modules.journal.domain.enums import JournalStatus
from app.modules.journal.infrastructure.models import JournalORM


def journal_signing_url(
    journal: JournalORM, *, now: datetime | None = None
) -> str | None:
    if (
        journal.status != JournalStatus.ACTIVE
        or journal.signed_at is not None
        or not journal.public_token
    ):
        return None
    now = now or datetime.now(timezone.utc)
    if journal.public_token_expires_at is not None and journal.public_token_expires_at <= now:
        return None
    base = settings.PUBLIC_APP_BASE_URL.rstrip("/")
    return f"{base}/acceptance/{quote(journal.public_token, safe='')}"
