from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from app.api.v1.deps import get_uow
from app.api.v1.rate_limit import rate_limit_public_files
from app.modules.files.application.api_service import PublicFilesService


router = APIRouter(prefix="/public/files", tags=["Public / Files"])


@router.get(
    "/{token}",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "Binary file stream",
            "content": {
                "application/octet-stream": {
                    "schema": {"type": "string", "format": "binary"}
                }
            },
        }
    },
)
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
        result = PublicFilesService.prepare_download(
            uow,
            token=token,
            aud=aud,
            ip=ip,
            user_agent=ua,
        )

        def gen():
            try:
                while True:
                    chunk = result.obj.read(1024 * 1024)
                    if not chunk:
                        break
                    yield chunk
            finally:
                try:
                    result.obj.close()
                except Exception:
                    pass
                try:
                    result.obj.release_conn()
                except Exception:
                    pass

        headers = {}
        headers["Content-Disposition"] = (
            f'attachment; filename="{result.file_name}"'
        )
        headers["Cache-Control"] = "no-store"
        headers["Pragma"] = "no-cache"

        return StreamingResponse(
            gen(),
            media_type=result.mime_type,
            headers=headers,
        )
