from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.modules.documents.infrastructure.models import (
    DocumentGenerationORM,
    DocumentTemplateORM,
)


class DocumentRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save_template(self, row: DocumentTemplateORM) -> None:
        self.session.add(row)

    def save_generation(self, row: DocumentGenerationORM) -> None:
        self.session.add(row)

    def get_template(
        self, *, company_id: uuid.UUID, template_id: uuid.UUID
    ) -> DocumentTemplateORM | None:
        return (
            self.session.query(DocumentTemplateORM)
            .filter(
                DocumentTemplateORM.company_id == company_id,
                DocumentTemplateORM.id == template_id,
            )
            .one_or_none()
        )

    def get_template_by_code(
        self, *, company_id: uuid.UUID, code: str
    ) -> DocumentTemplateORM | None:
        return (
            self.session.query(DocumentTemplateORM)
            .filter(
                DocumentTemplateORM.company_id == company_id,
                DocumentTemplateORM.code == code,
            )
            .one_or_none()
        )

    def list_templates(
        self, *, company_id: uuid.UUID, active_only: bool = False
    ) -> list[DocumentTemplateORM]:
        q = self.session.query(DocumentTemplateORM).filter(
            DocumentTemplateORM.company_id == company_id
        )
        if active_only:
            q = q.filter(DocumentTemplateORM.is_active.is_(True))
        return q.order_by(DocumentTemplateORM.created_at.desc()).all()

    def get_generation(
        self, *, company_id: uuid.UUID, generation_id: uuid.UUID
    ) -> DocumentGenerationORM | None:
        return (
            self.session.query(DocumentGenerationORM)
            .filter(
                DocumentGenerationORM.company_id == company_id,
                DocumentGenerationORM.id == generation_id,
            )
            .one_or_none()
        )

    def list_generations(
        self,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID | None = None,
        limit: int = 50,
    ) -> list[DocumentGenerationORM]:
        q = self.session.query(DocumentGenerationORM).filter(
            DocumentGenerationORM.company_id == company_id
        )
        if project_id is not None:
            q = q.filter(DocumentGenerationORM.project_id == project_id)
        return q.order_by(DocumentGenerationORM.created_at.desc()).limit(limit).all()
