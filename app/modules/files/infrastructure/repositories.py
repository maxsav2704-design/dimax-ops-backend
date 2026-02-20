from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.modules.files.infrastructure.models import (
    FileDownloadEventORM,
    FileDownloadTokenORM,
)


class FileTokenRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, row: FileDownloadTokenORM) -> None:
        self.session.add(row)

    def get_by_token(self, token: str) -> FileDownloadTokenORM | None:
        return (
            self.session.query(FileDownloadTokenORM)
            .filter(FileDownloadTokenORM.token == token)
            .one_or_none()
        )

    def consume(
        self,
        row: FileDownloadTokenORM,
        *,
        ip: str | None,
        user_agent: str | None,
    ) -> None:
        row.last_used_at = datetime.now(timezone.utc)
        row.last_used_ip = ip
        row.last_used_ua = user_agent
        row.uses_left -= 1
        self.session.add(row)

    def delete_expired_and_used(self) -> int:
        now = datetime.now(timezone.utc)
        q = self.session.query(FileDownloadTokenORM).filter(
            or_(
                FileDownloadTokenORM.expires_at <= now,
                FileDownloadTokenORM.uses_left <= 0,
            )
        )
        count = q.count()
        q.delete(synchronize_session=False)
        return count


class FileDownloadEventRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, ev: FileDownloadEventORM) -> None:
        self.session.add(ev)
