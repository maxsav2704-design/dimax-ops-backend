from uuid import UUID

from app.modules.audit.application.service import AuditService
from app.modules.rates.application.contact_dto import FactoryContactView, RegisterFactoryContact, RevokeFactoryContact
from app.modules.rates.infrastructure.contact_models import FactoryContactORM
from app.shared.domain.errors import Conflict, Forbidden, NotFound
from app.shared.infrastructure.db.base import utcnow


class FactoryContactService:
    @staticmethod
    def _lock_owner(uow, company_id, actor_user_id):
        if not uow.price_lists.lock_company(company_id):
            raise NotFound("Company unavailable")
        if not uow.price_lists.can_manage_factory_contact(company_id, actor_user_id):
            raise Forbidden("Only the company owner may approve the factory contact")

    @staticmethod
    def _revoke_pending(uow, company_id, actor_user_id, now, reason):
        for pending in uow.price_lists.pending_company_approvals(company_id):
            pending.revoked_at, pending.revoked_by = now, actor_user_id
            pending.revocation_reason = reason

    @staticmethod
    def register(uow, *, company_id: UUID, actor_user_id: UUID, body: RegisterFactoryContact):
        FactoryContactService._lock_owner(uow, company_id, actor_user_id)
        current = uow.price_lists.factory_contact(company_id)
        values = body.model_dump(exclude={"expected_contact_id"})
        values["recipient_email"] = str(body.recipient_email)
        if current and all(getattr(current, key) == value for key, value in values.items()):
            return FactoryContactView.model_validate(current)
        if body.expected_contact_id != (current.id if current else None):
            raise Conflict("Factory contact changed; reload before replacing it")
        now = utcnow()
        if current:
            current.revoked_at, current.revoked_by = now, actor_user_id
        FactoryContactService._revoke_pending(uow, company_id, actor_user_id, now,
                                             "Factory contact replaced by company owner")
        contact = FactoryContactORM(company_id=company_id, approved_by=actor_user_id, **values)
        uow.price_lists.add_factory_contact(contact)
        AuditService.add(uow, company_id=company_id, actor_user_id=actor_user_id,
            entity_type="FACTORY_CONTACT", entity_id=contact.id, action="APPROVE",
            before={"contact_id": str(current.id)} if current else None,
            after={**values, "contact_id": str(contact.id)})
        return FactoryContactView.model_validate(contact)

    @staticmethod
    def revoke(uow, *, company_id: UUID, actor_user_id: UUID, body: RevokeFactoryContact):
        FactoryContactService._lock_owner(uow, company_id, actor_user_id)
        current = uow.price_lists.factory_contact(company_id)
        if current is None:
            return
        if current.id != body.expected_contact_id:
            raise Conflict("Factory contact changed; reload before revoking it")
        now = utcnow()
        current.revoked_at, current.revoked_by = now, actor_user_id
        FactoryContactService._revoke_pending(uow, company_id, actor_user_id, now,
                                             "Factory contact revoked by company owner")
        AuditService.add(uow, company_id=company_id, actor_user_id=actor_user_id,
            entity_type="FACTORY_CONTACT", entity_id=current.id, action="REVOKE", reason=body.reason,
            after={"contact_id": str(current.id), "revoked_at": now.isoformat()})
