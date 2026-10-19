"""Owner-approved company rules for DIMAX AI (plan step 7).

The owner writes rules in plain language; the agent receives the current version as
company authority (trust level 2). Rules can never add tools or override the fixed
business rules of the runner. Every save is a new version and every reply records
the version it saw, so an answer can always be traced to the rules in force.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select

from app.modules.ai.api.schemas import AiRules
from app.modules.ai.infrastructure.models import AiCompanyRuleORM
from app.modules.audit.application.service import AuditService
from app.modules.identity.infrastructure.models import UserORM
from app.shared.domain.errors import ValidationError
from app.shared.infrastructure.db.base import utcnow

MAX_RULES_LENGTH = 4000


class AiRulesService:
    @staticmethod
    def current(uow, company_id: uuid.UUID) -> AiCompanyRuleORM | None:
        return uow.session.scalar(select(AiCompanyRuleORM).where(AiCompanyRuleORM.company_id == company_id)
                                  .order_by(AiCompanyRuleORM.version.desc()).limit(1))

    @staticmethod
    def view(uow, row: AiCompanyRuleORM | None) -> AiRules:
        if row is None:
            return AiRules(version=0, text="", updated_at=None, updated_by=None)
        author = uow.session.get(UserORM, row.updated_by_user_id) if row.updated_by_user_id else None
        return AiRules(version=row.version, text=row.text, updated_at=row.updated_at,
                       updated_by=author.full_name if author is not None else None)

    @staticmethod
    def set_rules(uow, *, company_id: uuid.UUID, actor_user_id: uuid.UUID, text: str) -> AiCompanyRuleORM:
        cleaned = (text or "").strip()
        if len(cleaned) > MAX_RULES_LENGTH:
            raise ValidationError(f"Rules must be at most {MAX_RULES_LENGTH} characters", field="text")
        current = AiRulesService.current(uow, company_id)
        if current is not None and current.text == cleaned:
            return current
        now = utcnow()
        row = AiCompanyRuleORM(id=uuid.uuid4(), company_id=company_id, version=(current.version if current else 0) + 1,
                               text=cleaned, updated_by_user_id=actor_user_id, created_at=now, updated_at=now)
        uow.session.add(row)
        uow.session.flush()
        # Metadata only: the rules text is readable through the rules endpoint, not through the audit.
        AuditService.add(uow, company_id=company_id, actor_user_id=actor_user_id, entity_type="AiCompanyRules",
                         entity_id=row.id, action="AI_RULES_UPDATED",
                         after={"version": row.version, "length": len(cleaned), "cleared": not cleaned})
        return row
