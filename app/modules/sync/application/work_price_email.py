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

KIND = "WORK_PRICE_INVITATION"
CODE_KIND = "WORK_PRICE_MAILBOX_CODE"


def _enqueue(uow, invitation, kind, data):
    cipher = AES.new(_key(), AES.MODE_GCM)
    cipher.update(f"{kind}:{invitation.company_id}:{invitation.id}".encode())
    ciphertext, tag = cipher.encrypt_and_digest(json.dumps(data).encode())
    message = OutboxMessageORM(company_id=invitation.company_id, channel=OutboxChannel.EMAIL,
        status=OutboxStatus.PENDING, correlation_id=None, attempts=0, max_attempts=5, scheduled_at=utcnow(),
        payload={"kind": kind, "approval_id": str(invitation.id), "to_email": invitation.recipient_email,
            "subject": "DIMAX: separate work price confirmation", "body_text": "Factory work price verification",
            "sealed_work_price": base64.b64encode(cipher.nonce + tag + ciphertext).decode()})
    uow.outbox.enqueue(message)
    uow.session.flush()
    return message


def enqueue_invitation(uow, invitation, token, base):
    return _enqueue(uow, invitation, KIND, {"token": token, "base": base})


def enqueue_code(uow, invitation, token, code):
    return _enqueue(uow, invitation, CODE_KIND,
        {"token": token, "code": code, "challenge_id": str(invitation.mailbox_challenge_id)})


def deliver(message, sender):
    from app.modules.rates.application.approval_verification import MAX_ATTEMPTS, code_digest
    from app.modules.sync.application.work_price_approval_service import WorkPriceApprovalService
    from app.shared.infrastructure.db.uow_sqlalchemy import SqlAlchemyUnitOfWork
    validate_mailbox_delivery()
    payload = message.payload
    try:
        kind = payload["kind"]
        if kind not in (KIND, CODE_KIND):
            raise ValueError()
        sealed = base64.b64decode(payload["sealed_work_price"], validate=True)
        cipher = AES.new(_key(), AES.MODE_GCM, nonce=sealed[:16])
        cipher.update(f'{kind}:{message.company_id}:{payload["approval_id"]}'.encode())
        data = json.loads(cipher.decrypt_and_verify(sealed[32:], sealed[16:32]))
        token = data["token"]
    except (KeyError, ValueError, TypeError):
        raise UnavailableInvitation("Invalid sealed work price message") from None
    # Hold the same company/work locks as confirmation through SMTP submission.
    with SqlAlchemyUnitOfWork() as uow:
        try:
            invitation, _, now = WorkPriceApprovalService._resolve(uow, token)
        except (NotFound, Conflict):
            raise UnavailableInvitation("Work price invitation is no longer pending") from None
        if (invitation.company_id != message.company_id or str(invitation.id) != payload["approval_id"]
                or invitation.recipient_email != payload["to_email"] or invitation.confirmed_at):
            raise UnavailableInvitation("Work price invitation recipient or state changed")
        scope = invitation.snapshot["proposal"]["scope"]
        title = "DIMAX: confirmation code for one work" if kind == CODE_KIND else "DIMAX: price approval for one work"
        context = (f'{invitation.recipient_name} / {invitation.factory_name}\n'
            f'{invitation.snapshot["company_name"]}\nProject: {scope["project_name"]}\n'
            f'Work: {scope["work_label"]}\nReference: {invitation.snapshot["reference"]}\n'
            f'Performed: {scope["missing_price"]["performed_at"]}\n'
            f'Quantity: {scope["quantity"]} {scope["unit"]}\n'
            f'Rate: {invitation.snapshot["proposal"]["rate"]} ILS\n'
            f'Total: {invitation.snapshot["proposal"]["amount"]} ILS\n')
        if kind == CODE_KIND:
            code = data.get("code", "")
            if (str(invitation.mailbox_challenge_id) != data.get("challenge_id")
                    or invitation.mailbox_attempts >= MAX_ATTEMPTS or not invitation.mailbox_code_expires_at
                    or invitation.mailbox_code_expires_at <= now
                    or not compare_digest(code_digest(invitation, code), invitation.mailbox_code_hash or "")):
                raise UnavailableInvitation("Verification code is no longer available")
            details = (f'Confirmation code: {code}\nValid until: {invitation.mailbox_code_expires_at.isoformat()}\n'
                'Enter this code only on the DIMAX work price confirmation page you opened. Do not share it. '
                'If you did not request it, ignore this email.')
            html_action = f'<p style="font-size:28px;font-weight:bold">{escape(code)}</p>'
        else:
            link = f'{data["base"]}/work-price-approval#{token}'
            details = f'Review and confirm: {link}\nValid until: {invitation.expires_at.isoformat()}'
            html_action = f'<p><a href="{escape(link, quote=True)}">Review this work and price</a></p>'
        disclaimer = ('Opening the link does not approve prices. Confirmation applies only to this work, '
            'does not change the company price list and does not accrue earnings. Do not forward this message.')
        html = ('<html><body style="font-family:Arial,sans-serif;color:#191919"><h1>DIMAX</h1>'
            f'<h2>{escape(title)}</h2><p>{escape(context).replace(chr(10), "<br>")}</p>{html_action}'
            f'<p>{escape(disclaimer)}</p></body></html>')
        sender.send(to_email=invitation.recipient_email, subject=title,
            body_text=f"{context}\n{details}\n\n{disclaimer}", body_html=html)
