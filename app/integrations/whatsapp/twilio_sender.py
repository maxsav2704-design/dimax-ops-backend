from __future__ import annotations

import requests

from app.core.config import settings


class TwilioWhatsAppSender:
    def send(
        self,
        *,
        to_phone_e164: str,
        body_text: str,
        media_url: str | None = None,
        status_callback_url: str | None = None,
    ) -> str:
        url = (
            f"https://api.twilio.com/2010-04-01/Accounts/"
            f"{settings.TWILIO_ACCOUNT_SID}/Messages.json"
        )
        data = {
            "From": settings.TWILIO_WHATSAPP_FROM,
            "To": f"whatsapp:{to_phone_e164}",
            "Body": body_text,
        }
        if media_url:
            data["MediaUrl"] = media_url
        if status_callback_url:
            data["StatusCallback"] = status_callback_url

        r = requests.post(
            url,
            data=data,
            auth=(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN),
            timeout=20,
        )
        if r.status_code >= 400:
            raise RuntimeError(f"Twilio error {r.status_code}: {r.text[:300]}")

        js = r.json()
        sid = js.get("sid")
        if not sid:
            raise RuntimeError("Twilio response missing sid")
        return sid
