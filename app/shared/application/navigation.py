from __future__ import annotations

from urllib.parse import quote_plus

from app.core.config import settings


def build_waze_url(*, address: str | None) -> str | None:
    if not settings.WAZE_NAVIGATION_ENABLED:
        return None
    if not address:
        return None
    value = address.strip()
    if not value:
        return None
    return f"{settings.WAZE_BASE_URL}?q={quote_plus(value)}&navigate=yes"
