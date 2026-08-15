from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.v1.deps import CurrentUser, get_current_user
from app.shared.domain.errors import NotFound


router = APIRouter(prefix="/media", tags=["Media"])


class MediaUrlResponse(BaseModel):
    url: str


@router.get("/{media_id}/url", response_model=MediaUrlResponse)
def get_media_url(
    media_id: UUID,
    _user: CurrentUser = Depends(get_current_user),
) -> MediaUrlResponse:
    raise NotFound("Media file not found", details={"media_id": str(media_id)})
