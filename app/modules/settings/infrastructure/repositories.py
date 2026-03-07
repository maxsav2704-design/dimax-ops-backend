from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.modules.identity.infrastructure.models import CompanyORM
from app.modules.settings.infrastructure.models import CommunicationTemplateORM


class CompanySettingsRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_id(self, *, company_id: uuid.UUID) -> CompanyORM | None:
        return (
            self.session.query(CompanyORM)
            .filter(CompanyORM.id == company_id)
            .one_or_none()
        )

    def save(self, company: CompanyORM) -> None:
        self.session.add(company)

    def list_templates(
        self,
        *,
        company_id: uuid.UUID,
        active_only: bool = False,
    ) -> list[CommunicationTemplateORM]:
        q = self.session.query(CommunicationTemplateORM).filter(
            CommunicationTemplateORM.company_id == company_id
        )
        if active_only:
            q = q.filter(CommunicationTemplateORM.is_active.is_(True))
        return q.order_by(CommunicationTemplateORM.name.asc()).all()

    def get_template(
        self,
        *,
        company_id: uuid.UUID,
        template_id: uuid.UUID,
    ) -> CommunicationTemplateORM | None:
        return (
            self.session.query(CommunicationTemplateORM)
            .filter(
                CommunicationTemplateORM.company_id == company_id,
                CommunicationTemplateORM.id == template_id,
            )
            .one_or_none()
        )

    def get_template_by_code(
        self,
        *,
        company_id: uuid.UUID,
        code: str,
    ) -> CommunicationTemplateORM | None:
        return (
            self.session.query(CommunicationTemplateORM)
            .filter(
                CommunicationTemplateORM.company_id == company_id,
                CommunicationTemplateORM.code == code,
            )
            .one_or_none()
        )

    def save_template(self, template: CommunicationTemplateORM) -> None:
        self.session.add(template)

    def delete_template(self, template: CommunicationTemplateORM) -> None:
        self.session.delete(template)
