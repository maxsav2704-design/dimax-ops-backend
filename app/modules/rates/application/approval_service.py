from __future__ import annotations

import hashlib
import json
import secrets
from datetime import timedelta
from hmac import compare_digest
from uuid import UUID

from app.core.config import settings
from app.modules.audit.application.service import AuditService
from app.modules.rates.application.approval_dto import (
    ApprovalPage, ApprovalSummary, ConfirmApproval, IssueApproval,
    IssuedApproval, PublicApproval, PublicApprovalLine,
)
from app.modules.rates.infrastructure.approval_models import FactoryPriceApprovalORM
from app.modules.rates.application.approval_email import enqueue_invitation, validate_email_delivery
from app.modules.rates.application.approval_verification import VerificationRejected, request_code, verify_code
from app.shared.domain.errors import Conflict, NotFound
from app.shared.infrastructure.db.base import utcnow


def _snapshot(uow, price_list, company_name: str) -> dict:
    items = sorted(uow.price_lists.items(price_list.company_id, price_list.id),
                   key=lambda item: (item.kind, str(item.door_type_id or item.addon_type_id)))
    return {
        "company_name": company_name, "version": price_list.version, "currency": price_list.currency,
        "reason": price_list.reason, "agreement_reference": price_list.agreement_reference,
        "items": [{"kind": item.kind, "target_id": str(item.door_type_id or item.addon_type_id),
                   "name": item.name, "unit": item.unit, "installer_price": format(item.installer_price, ".2f")}
                  for item in items],
    }


def _digest(price_list, snapshot: dict) -> str:
    document = {"company_id": str(price_list.company_id), "price_list_id": str(price_list.id), "snapshot": snapshot}
    return hashlib.sha256(json.dumps(document, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def approval_snapshot_matches(uow, price_list, invitation) -> bool:
    try:
        current = _snapshot(uow, price_list, invitation.snapshot["company_name"])
        return (compare_digest(_digest(price_list, current), invitation.snapshot_hash)
                and compare_digest(_digest(price_list, invitation.snapshot), invitation.snapshot_hash))
    except (KeyError, TypeError, ValueError):
        return False


class FactoryPriceApprovalService:
    @staticmethod
    def issue(uow, *, company_id: UUID, price_list_id: UUID, actor_user_id: UUID, body: IssueApproval):
        email_base = validate_email_delivery() if body.send_email else None
        if not uow.price_lists.lock_company(company_id):
            raise NotFound("Price list not found")
        price_list = uow.price_lists.get(company_id, price_list_id)
        if price_list is None:
            raise NotFound("Price list not found")
        if price_list.status != "DRAFT" or price_list.version != uow.price_lists.latest_version(company_id):
            raise Conflict("Only the latest draft can be sent for factory confirmation")
        contact = uow.price_lists.factory_contact(company_id)
        if contact is None:
            raise Conflict("The company owner must approve a factory contact first")
        if (body.factory_name != contact.factory_name or body.recipient_name != contact.recipient_name
                or str(body.recipient_email) != contact.recipient_email):
            raise Conflict("The recipient must match the owner-approved factory contact")
        now = utcnow()
        for previous in uow.price_lists.pending_approvals(company_id, price_list_id):
            previous.revoked_at, previous.revoked_by = now, actor_user_id
            previous.revocation_reason = "Replaced by a new invitation"
        token = secrets.token_urlsafe(32)
        snapshot = _snapshot(uow, price_list, uow.price_lists.company(company_id).name)
        if not snapshot["items"]:
            raise Conflict("An empty price list cannot be confirmed")
        invitation = FactoryPriceApprovalORM(
            company_id=company_id, price_list_id=price_list_id, created_by=actor_user_id,
            created_at=now, expires_at=now + timedelta(hours=body.expires_in_hours),
            token_hash=hashlib.sha256(token.encode()).hexdigest(), snapshot_hash=_digest(price_list, snapshot),
            snapshot=snapshot, factory_name=body.factory_name, recipient_name=body.recipient_name,
            recipient_email=str(body.recipient_email),
            factory_contact_id=contact.id,
        )
        uow.price_lists.add_approval(invitation)
        message = enqueue_invitation(uow, invitation, token, email_base) if email_base else None
        AuditService.add(
            uow, company_id=company_id, actor_user_id=actor_user_id, entity_type="FACTORY_PRICE_APPROVAL",
            entity_id=invitation.id, action="INVITE", after={"price_list_id": str(price_list_id),
                "version": price_list.version, "recipient_email": invitation.recipient_email,
                "expires_at": invitation.expires_at.isoformat()},
        )
        return IssuedApproval(
            invitation=ApprovalSummary.model_validate(invitation),
            confirmation_url=f"{settings.PUBLIC_APP_BASE_URL.rstrip('/')}/price-approval#{token}",
            email_outbox_id=message.id if message else None,
        )

    @staticmethod
    def history(uow, *, company_id: UUID, price_list_id: UUID, limit: int, offset: int):
        if uow.price_lists.get(company_id, price_list_id) is None:
            raise NotFound("Price list not found")
        rows, total = uow.price_lists.approval_page(company_id, price_list_id, limit, offset)
        return ApprovalPage(items=[ApprovalSummary.model_validate(row) for row in rows], total=total)

    @staticmethod
    def revoke(uow, *, company_id: UUID, price_list_id: UUID, approval_id: UUID, actor_user_id: UUID, reason: str):
        if not uow.price_lists.lock_company(company_id):
            raise NotFound("Invitation not found")
        invitation = uow.price_lists.approval(company_id, approval_id)
        if invitation is None or invitation.price_list_id != price_list_id:
            raise NotFound("Invitation not found")
        if invitation.confirmed_at is not None:
            raise Conflict("A factory decision cannot be revoked; create an amended price list")
        if invitation.revoked_at is None:
            invitation.revoked_at, invitation.revoked_by = utcnow(), actor_user_id
            invitation.revocation_reason = reason
            AuditService.add(uow, company_id=company_id, actor_user_id=actor_user_id,
                             entity_type="FACTORY_PRICE_APPROVAL", entity_id=invitation.id,
                             action="REVOKE", reason=reason[:500], after={"reason": reason})
        return ApprovalSummary.model_validate(invitation)

    @staticmethod
    def _resolve(uow, token: str):
        scope = uow.price_lists.approval_scope(hashlib.sha256(token.encode()).hexdigest())
        if scope is None or not uow.price_lists.lock_company(scope.company_id):
            raise NotFound("Invitation unavailable")
        # Re-read after the shared tenant lock: rotation, cancellation and confirmation use it too.
        invitation = uow.price_lists.approval(scope.company_id, scope.id)
        company = uow.price_lists.company(scope.company_id)
        now = utcnow()
        if (invitation is None or not company.is_active or invitation.revoked_at is not None
                or invitation.expires_at <= now):
            raise NotFound("Invitation unavailable")
        if invitation.confirmed_at is None:
            contact = uow.price_lists.factory_contact(scope.company_id)
            if (contact is None or invitation.factory_contact_id != contact.id
                    or any(getattr(invitation, key) != getattr(contact, key)
                           for key in ("factory_name", "recipient_name", "recipient_email"))):
                raise NotFound("Invitation unavailable")
        price_list = uow.price_lists.get(scope.company_id, invitation.price_list_id)
        if price_list is None or price_list.status == "CANCELLED":
            raise NotFound("Invitation unavailable")
        if invitation.confirmed_at is None and price_list.version != uow.price_lists.latest_version(scope.company_id):
            raise Conflict("This price-list version has been superseded")
        if not approval_snapshot_matches(uow, price_list, invitation):
            raise Conflict("The price list no longer matches this invitation")
        return invitation, price_list, now

    @staticmethod
    def _public(invitation) -> PublicApproval:
        snapshot = invitation.snapshot
        return PublicApproval(
            company_name=snapshot["company_name"], factory_name=invitation.factory_name,
            recipient_name=invitation.recipient_name, version=snapshot["version"], currency=snapshot["currency"],
            reason=snapshot["reason"], agreement_reference=snapshot["agreement_reference"],
            items=[PublicApprovalLine(**item) for item in snapshot["items"]],
            snapshot_hash=invitation.snapshot_hash, expires_at=invitation.expires_at,
            status="CONFIRMED" if invitation.confirmed_at else "PENDING",
            confirmed_at=invitation.confirmed_at, confirmed_name=invitation.confirmed_name,
            mailbox_verified_at=invitation.mailbox_verified_at,
        )

    @classmethod
    def preview(cls, uow, *, token: str):
        invitation, _, _ = cls._resolve(uow, token)
        return cls._public(invitation)

    @classmethod
    def request_code(cls, uow, *, token: str):
        invitation, _, now = cls._resolve(uow, token)
        return request_code(uow, invitation, token, now)

    @classmethod
    def confirm(cls, uow, *, body: ConfirmApproval, ip: str | None = None, user_agent: str | None = None):
        invitation, price_list, now = cls._resolve(uow, body.token)
        if body.expected_version != price_list.version or not compare_digest(body.snapshot_hash, invitation.snapshot_hash):
            raise Conflict("Confirmation does not match the displayed price list")
        if not verify_code(invitation, body.verification_code, now):
            return VerificationRejected()
        if invitation.confirmed_at is not None:
            if body.signer_name != invitation.confirmed_name:
                raise Conflict("This version already has an immutable factory decision")
            return cls._public(invitation)
        if price_list.status != "DRAFT":
            raise Conflict("This price list cannot be confirmed")
        invitation.confirmed_at, invitation.confirmed_name = now, body.signer_name
        invitation.mailbox_verified_at = now
        price_list.status = "CONFIRMED"
        AuditService.add(uow, company_id=invitation.company_id, actor_user_id=None,
            entity_type="FACTORY_PRICE_APPROVAL", entity_id=invitation.id, action="CONFIRM",
            ip=ip, user_agent=user_agent, after={
                "actor_kind": "FACTORY_REPRESENTATIVE", "factory_contact_id": str(invitation.factory_contact_id),
                "price_list_id": str(price_list.id), "version": price_list.version,
                "snapshot_hash": invitation.snapshot_hash, "confirmed_name": invitation.confirmed_name,
                "recipient_email": invitation.recipient_email, "confirmed_at": now.isoformat(),
                "mailbox_verified_at": now.isoformat(),
            })
        return cls._public(invitation)
