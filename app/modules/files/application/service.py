from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone, timedelta

from app.core.config import settings
from app.modules.files.infrastructure.models import FileDownloadTokenORM


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FileTokenService:
    @staticmethod
    def create_token_for_object(
        uow,
        *,
        company_id: uuid.UUID,
        bucket: str,
        object_key: str,
        mime_type: str,
        file_name: str | None,
        ttl_sec: int | None = None,
        uses: int | None = None,
        audience: str | None = None,
    ) -> str:
        token = secrets.token_urlsafe(32)
        ttl = ttl_sec if ttl_sec is not None else settings.FILE_TOKEN_TTL_SEC
        uses_left = uses if uses is not None else settings.FILE_TOKEN_USES

        row = FileDownloadTokenORM(
            company_id=company_id,
            token=token,
            bucket=bucket,
            object_key=object_key,
            mime_type=mime_type,
            file_name=file_name,
            expires_at=utcnow() + timedelta(seconds=ttl),
            uses_left=uses_left,
            audience=audience,
        )
        uow.file_tokens.create(row)
        return token

    @staticmethod
    def cleanup(uow) -> int:
        return uow.file_tokens.delete_expired_and_used()
