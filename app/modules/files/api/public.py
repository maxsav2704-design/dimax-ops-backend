from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from app.api.v1.deps import get_uow
from app.api.v1.rate_limit import rate_limit_public_files
from app.integrations.storage.storage_service import StorageService
from app.modules.files.infrastructure.models import FileDownloadEventORM
from app.shared.domain.errors import Forbidden, NotFound


router = APIRouter(prefix="/public/files", tags=["Public / Files"])


@router.get("/{token}")
def download(
    token: str,
    request: Request,
    aud: str | None = Query(default=None),
    _rl=Depends(rate_limit_public_files),
    uow=Depends(get_uow),
):
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")

    with uow:
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

        uow.file_tokens.consume(row, ip=ip, user_agent=ua)

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
                user_agent=ua,
                actor_user_id=None,
                correlation_id=None,
            )
        )

        obj = StorageService.get_object_stream(
            bucket=row.bucket, object_key=row.object_key
        )

        def gen():
            try:
                while True:
                    chunk = obj.read(1024 * 1024)
                    if not chunk:
                        break
                    yield chunk
            finally:
                try:
                    obj.close()
                except Exception:
                    pass
                try:
                    obj.release_conn()
                except Exception:
                    pass

        headers = {}
        fname = row.file_name or "file"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
        headers["Cache-Control"] = "no-store"
        headers["Pragma"] = "no-cache"

        return StreamingResponse(
            gen(),
            media_type=row.mime_type or "application/octet-stream",
            headers=headers,
        )
