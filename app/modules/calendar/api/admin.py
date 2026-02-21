from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.v1.deps import CurrentUser, get_uow, require_admin
from app.modules.calendar.api.schemas import (
    EventCreateResponse,
    EventCreateBody,
    EventListResponse,
    EventUpdateBody,
    OkResponse,
)
from app.modules.calendar.application.api_service import CalendarApiService


router = APIRouter(prefix="/admin/calendar", tags=["Admin / Calendar"])


@router.get("/events", response_model=EventListResponse)
def list_events(
    starts_at: datetime = Query(...),
    ends_at: datetime = Query(...),
    installer_id: UUID | None = Query(default=None),
    project_id: UUID | None = Query(default=None),
    event_type: str | None = Query(default=None),
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return CalendarApiService.list_events(
            uow,
            company_id=user.company_id,
            starts_at=starts_at,
            ends_at=ends_at,
            installer_id=installer_id,
            project_id=project_id,
            event_type=event_type,
        )


@router.post("/events", response_model=EventCreateResponse)
def create_event(
    body: EventCreateBody,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        return CalendarApiService.create_event(
            uow,
            company_id=user.company_id,
            title=body.title,
            event_type=body.event_type,
            starts_at=body.starts_at,
            ends_at=body.ends_at,
            location=body.location,
            description=body.description,
            project_id=body.project_id,
            installer_ids=list(body.installer_ids),
        )


@router.patch("/events/{event_id}", response_model=OkResponse)
def update_event(
    event_id: UUID,
    body: EventUpdateBody,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        CalendarApiService.update_event(
            uow,
            company_id=user.company_id,
            event_id=event_id,
            payload=body.model_dump(exclude_unset=True),
        )
    return OkResponse()


@router.delete("/events/{event_id}", response_model=OkResponse)
def delete_event(
    event_id: UUID,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        CalendarApiService.delete_event(
            uow,
            company_id=user.company_id,
            event_id=event_id,
        )
    return OkResponse()
