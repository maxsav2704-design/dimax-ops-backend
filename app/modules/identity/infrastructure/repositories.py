from __future__ import annotations

import uuid
from sqlalchemy.orm import Session

from app.modules.identity.domain.enums import UserRole
from app.modules.identity.infrastructure.models import UserORM


class UserRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, user: UserORM) -> None:
        self.session.add(user)

    def get_by_email(
        self, *, company_id: uuid.UUID, email: str
    ) -> UserORM | None:
        return (
            self.session.query(UserORM)
            .filter(
                UserORM.company_id == company_id,
                UserORM.email == email,
                UserORM.is_active.is_(True),
            )
            .one_or_none()
        )

    def get_by_id(
        self, *, company_id: uuid.UUID, user_id: uuid.UUID
    ) -> UserORM | None:
        return (
            self.session.query(UserORM)
            .filter(
                UserORM.company_id == company_id,
                UserORM.id == user_id,
                UserORM.is_active.is_(True),
            )
            .one_or_none()
        )

    def list_active_emails_by_role(
        self, *, company_id: uuid.UUID, role: UserRole
    ) -> list[str]:
        rows = (
            self.session.query(UserORM.email)
            .filter(
                UserORM.company_id == company_id,
                UserORM.role == role,
                UserORM.is_active.is_(True),
            )
            .order_by(UserORM.email.asc())
            .all()
        )
        return [str(row[0]).strip().lower() for row in rows if row[0]]
