from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import timedelta
from uuid import uuid4

from app.modules.rates.application.approval_dto import RequestedApprovalCode
from app.modules.rates.application.approval_email import _key, enqueue_code, validate_mailbox_delivery
from app.shared.domain.errors import Conflict, TooManyRequests

MAX_ATTEMPTS = 5
MAX_REQUESTS = 10
CODE_LIFETIME = timedelta(minutes=10)
RESEND_DELAY = timedelta(seconds=60)


@dataclass(frozen=True)
class VerificationRejected:
    """Return through the UOW so failed attempts commit before the HTTP error."""


def code_digest(invitation, code: str) -> str:
    purpose = getattr(invitation, "mailbox_purpose", "factory-mailbox-v1")
    context = (f"{purpose}:{invitation.company_id}:{invitation.id}:"
               f"{invitation.mailbox_challenge_id}:{invitation.snapshot_hash}:"
               f"{invitation.recipient_email}:{code}")
    return hmac.new(_key(), context.encode(), hashlib.sha256).hexdigest()


def request_code(uow, invitation, token: str, now, *, enqueue=enqueue_code) -> RequestedApprovalCode:
    if invitation.confirmed_at:
        raise Conflict("This version already has an immutable factory decision")
    if invitation.mailbox_attempts >= MAX_ATTEMPTS or invitation.mailbox_requests >= MAX_REQUESTS:
        raise TooManyRequests("Mailbox verification limit reached; request a new invitation")
    if invitation.mailbox_requested_at and now < invitation.mailbox_requested_at + RESEND_DELAY:
        raise TooManyRequests("Wait before requesting another verification code")
    validate_mailbox_delivery()
    code = f"{secrets.randbelow(1_000_000):06d}"
    invitation.mailbox_challenge_id = uuid4()
    invitation.mailbox_code_hash = code_digest(invitation, code)
    invitation.mailbox_requested_at = now
    invitation.mailbox_code_expires_at = min(now + CODE_LIFETIME, invitation.expires_at)
    invitation.mailbox_requests += 1
    # Resending invalidates the previous code, never the invitation's failed-attempt budget.
    enqueue(uow, invitation, token, code)
    return RequestedApprovalCode(expires_at=invitation.mailbox_code_expires_at, resend_after=now + RESEND_DELAY)


def verify_code(invitation, code: str | None, now) -> bool:
    if not code or not invitation.mailbox_code_hash:
        return False
    if invitation.mailbox_attempts >= MAX_ATTEMPTS:
        return False
    if not invitation.confirmed_at and now >= invitation.mailbox_code_expires_at:
        return False
    matches = hmac.compare_digest(code_digest(invitation, code), invitation.mailbox_code_hash)
    if not matches and not invitation.confirmed_at:
        invitation.mailbox_attempts += 1
    # Exact retries of a recorded decision remain safe even after the code expires.
    return matches
