from __future__ import annotations

import smtplib
from email.message import EmailMessage
from pathlib import Path

from app.core.config import settings


class SmtpEmailSender:
    def send(
        self,
        *,
        to_email: str,
        subject: str,
        body_text: str,
        attachment_path: str | None = None,
        attachment_name: str | None = None,
    ) -> None:
        msg = EmailMessage()
        msg["From"] = settings.SMTP_FROM
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.set_content(body_text)

        if attachment_path:
            p = Path(attachment_path)
            data = p.read_bytes()
            name = attachment_name or p.name
            msg.add_attachment(
                data, maintype="application", subtype="pdf", filename=name
            )

        with smtplib.SMTP(
            settings.SMTP_HOST, settings.SMTP_PORT, timeout=20
        ) as s:
            if settings.SMTP_TLS:
                s.starttls()
            if settings.SMTP_USER:
                s.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            s.send_message(msg)
