from __future__ import annotations

import base64
import ipaddress
import json
from html import escape
from urllib.parse import urlsplit

from Crypto.Cipher import AES
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config import settings
from app.modules.outbox.domain.enums import OutboxChannel, OutboxStatus
from app.modules.outbox.infrastructure.models import OutboxMessageORM
from app.shared.domain.errors import Conflict, NotFound, ValidationError
from app.shared.infrastructure.db.base import utcnow

KIND = "FACTORY_PRICE_INVITATION"


class ApprovalEmailSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    FACTORY_APPROVAL_EMAIL_KEY: SecretStr = SecretStr("")


email_settings = ApprovalEmailSettings()


def _key() -> bytes:
    try:
        key = base64.b64decode(email_settings.FACTORY_APPROVAL_EMAIL_KEY.get_secret_value(), validate=True)
        if len(key) != 32:
            raise ValueError()
        return key
    except ValueError:
        raise ValidationError("Factory invitation email encryption is not configured") from None


def validate_email_delivery() -> str:
    if not settings.EMAIL_ENABLED:
        raise ValidationError("Email delivery is disabled")
    _key()
    base = settings.PUBLIC_APP_BASE_URL.rstrip("/")
    try:
        url = urlsplit(base)
        host = (url.hostname or "").lower().rstrip(".")
        port = url.port
    except ValueError:
        raise ValidationError("Factory invitation email requires a valid HTTPS application URL") from None
    try:
        private = not ipaddress.ip_address(host).is_global
    except ValueError:
        private = host in {"localhost", ""} or host.endswith((".localhost", ".local"))
    if url.scheme != "https" or private or port == 0 or url.username or url.password or url.query or url.fragment:
        raise ValidationError("Factory invitation email requires a public HTTPS application URL")
    return base


def enqueue_invitation(uow, invitation, token: str, base: str) -> OutboxMessageORM:
    # Bind the sealed link to its tenant and invitation, not a reusable generic mail body.
    identity = f"{invitation.company_id}:{invitation.id}"
    cipher = AES.new(_key(), AES.MODE_GCM)
    cipher.update(identity.encode())
    ciphertext, tag = cipher.encrypt_and_digest(json.dumps({"token": token, "base": base}).encode())
    message = OutboxMessageORM(
        company_id=invitation.company_id, channel=OutboxChannel.EMAIL, status=OutboxStatus.PENDING,
        correlation_id=None, attempts=0, max_attempts=5, scheduled_at=utcnow(),
        payload={"kind": KIND, "approval_id": str(invitation.id), "to_email": invitation.recipient_email,
                 "subject": "DIMAX: factory price confirmation", "body_text": "Factory price invitation",
                 "sealed_link": base64.b64encode(cipher.nonce + tag + ciphertext).decode()},
    )
    uow.outbox.enqueue(message)
    uow.session.flush()
    return message


class UnavailableInvitation(Exception):
    pass


def deliver_invitation(message, sender) -> None:
    from app.modules.rates.application.approval_service import FactoryPriceApprovalService
    from app.shared.infrastructure.db.uow_sqlalchemy import SqlAlchemyUnitOfWork

    if not settings.EMAIL_ENABLED:
        raise ValidationError("Email delivery is disabled")
    payload = message.payload
    try:
        sealed = base64.b64decode(payload["sealed_link"], validate=True)
        cipher = AES.new(_key(), AES.MODE_GCM, nonce=sealed[:16])
        cipher.update(f'{message.company_id}:{payload["approval_id"]}'.encode())
        link_data = json.loads(cipher.decrypt_and_verify(sealed[32:], sealed[16:32]))
    except (KeyError, ValueError, TypeError):
        raise UnavailableInvitation("Invalid sealed invitation") from None
    # Keep the company lock through SMTP submission so revocation cannot pass the check mid-send.
    with SqlAlchemyUnitOfWork() as uow:
        try:
            invitation, _, _ = FactoryPriceApprovalService._resolve(uow, link_data["token"])
        except (NotFound, Conflict):
            raise UnavailableInvitation("Invitation is no longer pending") from None
        if (invitation.company_id != message.company_id or str(invitation.id) != payload["approval_id"]
                or invitation.recipient_email != payload["to_email"] or invitation.confirmed_at):
            raise UnavailableInvitation("Invitation recipient or state changed")
        link = f'{link_data["base"]}/price-approval#{link_data["token"]}'
        snapshot = invitation.snapshot
        title = f'DIMAX: price list v{snapshot["version"]}'
        body = (f'{invitation.recipient_name},\n\n{snapshot["company_name"]} requests confirmation of '
                f'price list v{snapshot["version"]} for {invitation.factory_name}.\n'
                f'Agreement: {snapshot["agreement_reference"]}\n'
                f'Valid until: {invitation.expires_at.isoformat()}\n\nReview and confirm: {link}\n\n'
                'Opening this link does not confirm prices. Share it only with the named representative. '
                'Confirmation does not activate the price list or change existing earnings.')
        html = (f'<html><body style="font-family:Arial,sans-serif;color:#191919">'
                f'<h1 style="font-size:24px">DIMAX</h1><h2>{escape(title)}</h2>'
                f'<p>{escape(invitation.recipient_name)} · {escape(invitation.factory_name)}</p>'
                f'<p>{escape(snapshot["company_name"])}<br>Agreement: {escape(snapshot["agreement_reference"])}</p>'
                f'<p>Valid until: {escape(invitation.expires_at.isoformat())}</p>'
                f'<p><a href="{escape(link, quote=True)}" style="display:inline-block;padding:14px 20px;'
                'background:#ffcd35;color:#191919;text-decoration:none;border-radius:6px">Review and confirm prices</a></p>'
                '<p>Opening this link does not confirm prices. Do not forward it. Confirmation does not '
                'activate the price list or change existing earnings.</p></body></html>')
        sender.send(to_email=invitation.recipient_email, subject=title, body_text=body, body_html=html)
