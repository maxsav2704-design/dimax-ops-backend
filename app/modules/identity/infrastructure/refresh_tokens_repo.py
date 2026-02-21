from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.modules.identity.infrastructure.refresh_tokens_models import RefreshTokenORM


class RefreshTokenRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, token: RefreshTokenORM) -> None:
        self.session.add(token)

    def get_active_by_jti(
        self, *, company_id: uuid.UUID, jti: str
    ) -> RefreshTokenORM | None:
        return (
            self.session.query(RefreshTokenORM)
            .filter(
                RefreshTokenORM.company_id == company_id,
                RefreshTokenORM.jti == jti,
                RefreshTokenORM.revoked_at.is_(None),
            )
            .one_or_none()
        )

    def revoke(
        self,
        token: RefreshTokenORM,
        *,
        revoked_at: datetime,
        replaced_by_jti: str | None = None,
    ) -> None:
        token.revoked_at = revoked_at
        token.replaced_by_jti = replaced_by_jti
        self.session.add(token)

    def revoke_all_active_by_user(
        self,
        *,
        company_id: uuid.UUID,
        user_id: uuid.UUID,
        revoked_at: datetime,
    ) -> int:
        q = self.session.query(RefreshTokenORM).filter(
            RefreshTokenORM.company_id == company_id,
            RefreshTokenORM.user_id == user_id,
            RefreshTokenORM.revoked_at.is_(None),
        )
        count = q.count()
        q.update(
            {
                RefreshTokenORM.revoked_at: revoked_at,
                RefreshTokenORM.replaced_by_jti: None,
            },
            synchronize_session=False,
        )
        return count
