from __future__ import annotations

import uuid
from sqlalchemy.orm import Session

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
