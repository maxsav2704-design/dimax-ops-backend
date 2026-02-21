from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from app.integrations.storage.storage_service import StorageService
from app.modules.files.api.admin_schemas import (
    FileDownloadEventDTO,
    FileDownloadEventsResponse,
)
from app.modules.files.infrastructure.models import FileDownloadEventORM
from app.shared.domain.errors import Forbidden, NotFound


@dataclass(frozen=True)
class PublicFileDownloadResult:
    obj: Any
    mime_type: str
    file_name: str


class FilesAdminService:
    @staticmethod
    def list_downloads(
        uow,
        *,
        company_id: UUID,
        journal_id: UUID | None,
        limit: int,
    ) -> FileDownloadEventsResponse:
        q = uow.session.query(FileDownloadEventORM).filter(
            FileDownloadEventORM.company_id == company_id
        )
        if journal_id is not None:
            q = q.filter(FileDownloadEventORM.correlation_id == journal_id)

        rows = q.order_by(FileDownloadEventORM.created_at.desc()).limit(limit).all()
        return FileDownloadEventsResponse(
            items=[
                FileDownloadEventDTO(
                    created_at=row.created_at,
                    source=row.source,
                    correlation_id=row.correlation_id,
                    ip=row.ip,
                    user_agent=row.user_agent,
                    actor_user_id=row.actor_user_id,
                    file_name=row.file_name,
                )
                for row in rows
            ]
        )


class PublicFilesService:
    @staticmethod
    def prepare_download(
        uow,
        *,
        token: str,
        aud: str | None,
        ip: str | None,
        user_agent: str | None,
    ) -> PublicFileDownloadResult:
        row = uow.file_tokens.get_by_token(token)
        if not row:
            raise NotFound("File token not found")

        now = datetime.now(timezone.utc)
        if row.expires_at <= now:
            raise Forbidden("File token expired")

        if row.uses_left <= 0:
            raise Forbidden("File token already used")

        if row.audience is not None and aud != row.audience:
            raise Forbidden("Invalid token audience")

        uow.file_tokens.consume(row, ip=ip, user_agent=user_agent)

        uow.file_download_events.add(
            FileDownloadEventORM(
                company_id=row.company_id,
                source="PUBLIC_TOKEN",
                token=row.token,
                object_key=row.object_key,
                bucket=row.bucket,
                mime_type=row.mime_type,
                file_name=row.file_name,
                ip=ip,
                user_agent=user_agent,
                actor_user_id=None,
                correlation_id=None,
            )
        )

        obj = StorageService.get_object_stream(
            bucket=row.bucket,
            object_key=row.object_key,
        )
        return PublicFileDownloadResult(
            obj=obj,
            mime_type=row.mime_type or "application/octet-stream",
            file_name=row.file_name or "file",
        )
