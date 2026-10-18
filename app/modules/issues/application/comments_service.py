from __future__ import annotations

import uuid

from app.modules.audit.application.service import AuditService
from app.modules.identity.infrastructure.models import UserORM
from app.modules.issues.api.schemas import IssueCommentDTO
from app.modules.issues.infrastructure.models import IssueCommentORM, IssueORM
from app.shared.domain.errors import ValidationError


class IssueCommentsService:
    """Comments on an issue: the office and the installer add to the thread,
    nobody replaces anybody's text. Visibility of the issue itself is checked
    by the caller (admin scope or installer assignment)."""

    @staticmethod
    def list_comments(uow, *, company_id: uuid.UUID, issue_id: uuid.UUID) -> list[IssueCommentDTO]:
        rows = (
            uow.session.query(IssueCommentORM)
            .filter(IssueCommentORM.company_id == company_id, IssueCommentORM.issue_id == issue_id)
            .order_by(IssueCommentORM.created_at.asc(), IssueCommentORM.id.asc())
            .all()
        )
        return [
            IssueCommentDTO(
                id=row.id,
                body=row.body,
                author_name=row.author_name,
                author_user_id=row.author_user_id,
                created_at=row.created_at,
            )
            for row in rows
        ]

    @staticmethod
    def add_comment(
        uow,
        *,
        company_id: uuid.UUID,
        issue: IssueORM,
        author_user_id: uuid.UUID,
        author_role: str,
        body: str,
    ) -> IssueCommentDTO:
        text = (body or "").strip()
        if not text:
            raise ValidationError("Comment text is required", field="body")
        if len(text) > 2000:
            raise ValidationError("Comment must be at most 2000 characters", field="body")
        author = uow.session.get(UserORM, author_user_id)
        row = IssueCommentORM(
            company_id=company_id,
            issue_id=issue.id,
            author_user_id=author_user_id,
            author_role=author_role,
            author_name=author.full_name if author is not None else None,
            body=text,
        )
        uow.session.add(row)
        uow.session.flush()
        AuditService.add(
            uow,
            company_id=company_id,
            actor_user_id=author_user_id,
            entity_type="issue",
            entity_id=issue.id,
            action="ISSUE_COMMENT",
            after={"comment_id": str(row.id), "author_role": author_role},
        )
        return IssueCommentDTO(
            id=row.id, body=row.body, author_name=row.author_name,
            author_user_id=row.author_user_id, created_at=row.created_at,
        )
