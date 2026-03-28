from __future__ import annotations

from urllib.parse import quote_plus, urlparse

from app.core.config import settings


def normalize_phone(raw: str | None) -> str | None:
    if raw is None:
        return None
    value = str(raw).strip()
    if not value:
        return None

    digits = "".join(ch for ch in value if ch.isdigit() or ch == "+")
    if not digits:
        return None
    if digits.startswith("00"):
        digits = f"+{digits[2:]}"
    if digits.startswith("0"):
        digits = f"+972{digits[1:]}"
    elif not digits.startswith("+"):
        digits = f"+{digits}"
    digits = f"+{''.join(ch for ch in digits if ch.isdigit())}"
    if len(digits) < 12 or len(digits) > 13:
        return None
    return digits


def build_project_address(
    *,
    address: str | None = None,
    street: str | None = None,
    building: str | None = None,
    city: str | None = None,
    entrance: str | None = None,
) -> str | None:
    structured = [part.strip() for part in [street, building, city] if part and part.strip()]
    if structured:
        value = ", ".join(structured)
        if entrance and entrance.strip():
            value = f"{value}, {entrance.strip()}"
        return value
    if not address:
        return None
    value = address.strip()
    return value or None


def build_waze_url(
    *,
    address: str | None = None,
    lat: float | str | None = None,
    lng: float | str | None = None,
    manual_url: str | None = None,
) -> str | None:
    if not settings.WAZE_NAVIGATION_ENABLED:
        return None
    if manual_url and str(manual_url).strip():
        return str(manual_url).strip()
    if lat is not None and lng is not None:
        return f"{settings.WAZE_BASE_URL}?ll={lat},{lng}&navigate=yes"
    if not address:
        return None
    value = address.strip()
    if not value:
        return None
    return f"{settings.WAZE_BASE_URL}?q={quote_plus(value)}&navigate=yes"


def build_whatsapp_url(*, phone: str | None, message: str | None = None) -> str | None:
    normalized = normalize_phone(phone)
    if not normalized:
        return None
    wa_phone = normalized.replace("+", "")
    if message and message.strip():
        return f"https://wa.me/{wa_phone}?text={quote_plus(message.strip())}"
    return f"https://wa.me/{wa_phone}"


def build_call_url(*, phone: str | None) -> str | None:
    normalized = normalize_phone(phone)
    if not normalized:
        return None
    return f"tel:{normalized}"


def is_valid_http_url(value: str | None) -> bool:
    if not value or not value.strip():
        return True
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
