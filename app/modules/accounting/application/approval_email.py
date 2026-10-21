import base64
import json
from hmac import compare_digest
from html import escape

from Crypto.Cipher import AES

from app.modules.outbox.domain.enums import OutboxChannel, OutboxStatus
from app.modules.outbox.infrastructure.models import OutboxMessageORM
from app.modules.rates.application.approval_email import _key, validate_mailbox_delivery, UnavailableInvitation
from app.shared.domain.errors import Conflict, NotFound
from app.shared.infrastructure.db.base import utcnow

KIND = "COMMERCIAL_APPROVAL_INVITATION"
CODE_KIND = "COMMERCIAL_APPROVAL_MAILBOX_CODE"


def _enqueue(uow, invitation, kind, data):
    cipher = AES.new(_key(), AES.MODE_GCM)
    cipher.update(f"{kind}:{invitation.company_id}:{invitation.id}".encode())
    ciphertext, tag = cipher.encrypt_and_digest(json.dumps(data).encode())
    message = OutboxMessageORM(company_id=invitation.company_id, channel=OutboxChannel.EMAIL,
        status=OutboxStatus.PENDING, correlation_id=None, attempts=0, max_attempts=5, scheduled_at=utcnow(),
        payload={"kind": kind, "approval_id": str(invitation.id), "to_email": invitation.recipient_email,
            "subject": "DIMAX: commercial agreement confirmation", "body_text": "Commercial agreement verification",
            "sealed_commercial": base64.b64encode(cipher.nonce + tag + ciphertext).decode()})
    uow.outbox.enqueue(message)
    uow.session.flush()
    return message


def enqueue_invitation(uow, invitation, token, base):
    return _enqueue(uow, invitation, KIND, {"token": token, "base": base})


def enqueue_code(uow, invitation, token, code):
    return _enqueue(uow, invitation, CODE_KIND,
        {"token": token, "code": code, "challenge_id": str(invitation.mailbox_challenge_id)})


def deliver(message, sender):
    from app.modules.accounting.application.approval_service import CommercialApprovalService
    from app.modules.rates.application.approval_verification import MAX_ATTEMPTS, code_digest
    from app.shared.infrastructure.db.uow_sqlalchemy import SqlAlchemyUnitOfWork
    validate_mailbox_delivery()
    payload = message.payload
    try:
        kind = payload["kind"]
        if kind not in (KIND, CODE_KIND):
            raise ValueError()
        sealed = base64.b64decode(payload["sealed_commercial"], validate=True)
        cipher = AES.new(_key(), AES.MODE_GCM, nonce=sealed[:16])
        cipher.update(f'{kind}:{message.company_id}:{payload["approval_id"]}'.encode())
        data = json.loads(cipher.decrypt_and_verify(sealed[32:], sealed[16:32]))
        token = data["token"]
    except (KeyError, ValueError, TypeError):
        raise UnavailableInvitation("Invalid sealed commercial message") from None
    # Contact rotation, new versions, confirmation and SMTP submission share this lock.
    with SqlAlchemyUnitOfWork() as uow:
        try:
            row, now = CommercialApprovalService._resolve(uow, token)
        except (NotFound, Conflict):
            raise UnavailableInvitation("Commercial invitation is no longer pending") from None
        if (row.company_id != message.company_id or str(row.id) != payload["approval_id"]
                or row.recipient_email != payload["to_email"] or row.confirmed_at):
            raise UnavailableInvitation("Commercial invitation recipient or state changed")
        snapshot = row.snapshot
        context = (f'{row.recipient_name} / {row.factory_name}\n{snapshot["company_name"]}\n'
            f'Contract: {snapshot["contract_reference"]}\nFactory legal name: {snapshot["terms"]["factory_legal_name"]}\n'
            f'Terms version: {snapshot["terms"]["version"]}\nCommercial price version: {snapshot["price"]["version"]}\n'
            'Factory pays DIMAX. ILS, excluding VAT. This is NOT the installer price list.\n')
        if snapshot["is_demo"]:
            context = 'TEST ONLY: fictitious contract and prices, not commercial evidence.\n' + context
        if kind == CODE_KIND:
            code = data.get("code", "")
            if (str(row.mailbox_challenge_id) != data.get("challenge_id") or row.mailbox_attempts >= MAX_ATTEMPTS
                    or not row.mailbox_code_expires_at or row.mailbox_code_expires_at <= now
                    or not compare_digest(code_digest(row, code), row.mailbox_code_hash or "")):
                raise UnavailableInvitation("Verification code is no longer available")
            details = f'Confirmation code: {code}\nValid until: {row.mailbox_code_expires_at.isoformat()}'
            action = f'<p style="font-size:28px;font-weight:bold">{escape(code)}</p>'
        else:
            link = f'{data["base"]}/commercial-approval#{token}'
            details = f'Review both versions: {link}\nValid until: {row.expires_at.isoformat()}'
            action = f'<p><a href="{escape(link, quote=True)}">Review contract terms and commercial prices</a></p>'
        disclaimer = ('Opening this link does not confirm anything. Confirm only the two displayed versions. '
            'This is not a work journal signature, invoice, payment or installer earning. Do not forward this email. '
            'If you did not request a code, ignore it.')
        html = ('<html><body style="font-family:Arial,sans-serif;color:#191919"><h1>DIMAX</h1>'
            f'<p>{escape(context).replace(chr(10), "<br>")}</p>{action}<p>{escape(disclaimer)}</p></body></html>')
        sender.send(to_email=row.recipient_email, subject="DIMAX: commercial agreement confirmation",
            body_text=f"{context}\n{details}\n\n{disclaimer}", body_html=html)
