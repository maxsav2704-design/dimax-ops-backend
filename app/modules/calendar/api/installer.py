from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.v1.acl import get_current_installer_id
from app.api.v1.deps import CurrentUser, get_uow, require_installer
from app.modules.calendar.api.schemas import EventListResponse
from app.modules.calendar.application.api_service import CalendarApiService


router = APIRouter(prefix="/installer/calendar", tags=["Installer / Calendar"])


@router.get("/events", response_model=EventListResponse)
def list_my_events(
    starts_at: datetime = Query(...),
    ends_at: datetime = Query(...),
    user: CurrentUser = Depends(require_installer),
    installer_id: UUID = Depends(get_current_installer_id),
    uow=Depends(get_uow),
):
    with uow:
        return CalendarApiService.list_events(
            uow,
            company_id=user.company_id,
            starts_at=starts_at,
            ends_at=ends_at,
            installer_id=installer_id,
        )
