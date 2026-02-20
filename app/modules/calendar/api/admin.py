from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.v1.deps import CurrentUser, get_uow, require_admin
from app.modules.calendar.api.schemas import (
    EventCreateBody,
    EventDTO,
    EventListResponse,
    EventUpdateBody,
    OkResponse,
)
from app.modules.calendar.application.use_cases import CalendarUseCases


router = APIRouter(prefix="/admin/calendar", tags=["Admin / Calendar"])


def _event_type_value(e) -> str:
    return e.event_type.value if hasattr(e.event_type, "value") else str(e.event_type)


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
        events = uow.calendar.list_range(
            company_id=user.company_id,
            starts_at=starts_at,
            ends_at=ends_at,
            installer_id=installer_id,
            project_id=project_id,
            event_type=event_type,
        )
        items = []
        for e in events:
            assignees = uow.calendar.get_assignee_ids(
                company_id=user.company_id, event_id=e.id
            )
            items.append(
                EventDTO(
                    id=e.id,
                    title=e.title,
                    event_type=_event_type_value(e),
                    starts_at=e.starts_at,
                    ends_at=e.ends_at,
                    location=e.location,
                    description=e.description,
                    project_id=e.project_id,
                    installer_ids=assignees,
                )
            )
        return EventListResponse(items=items)


@router.post("/events", response_model=dict)
def create_event(
    body: EventCreateBody,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        e = CalendarUseCases.create_event(
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
        return {"id": str(e.id)}


@router.patch("/events/{event_id}", response_model=OkResponse)
def update_event(
    event_id: UUID,
    body: EventUpdateBody,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        payload = body.model_dump(exclude_unset=True)
        if "installer_ids" in payload and payload["installer_ids"] is not None:
            payload["installer_ids"] = list(payload["installer_ids"])
        CalendarUseCases.update_event(
            uow,
            company_id=user.company_id,
            event_id=event_id,
            **payload,
        )
    return OkResponse()


@router.delete("/events/{event_id}", response_model=OkResponse)
def delete_event(
    event_id: UUID,
    user: CurrentUser = Depends(require_admin),
    uow=Depends(get_uow),
):
    with uow:
        CalendarUseCases.delete_event(
            uow,
            company_id=user.company_id,
            event_id=event_id,
        )
    return OkResponse()
