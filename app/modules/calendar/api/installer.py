from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.v1.acl import get_current_installer_id
from app.api.v1.deps import CurrentUser, get_uow, require_installer
from app.modules.calendar.api.schemas import EventDTO, EventListResponse


router = APIRouter(prefix="/installer/calendar", tags=["Installer / Calendar"])


def _event_type_value(e) -> str:
    return e.event_type.value if hasattr(e.event_type, "value") else str(e.event_type)


@router.get("/events", response_model=EventListResponse)
def list_my_events(
    starts_at: datetime = Query(...),
    ends_at: datetime = Query(...),
    user: CurrentUser = Depends(require_installer),
    installer_id: UUID = Depends(get_current_installer_id),
    uow=Depends(get_uow),
):
    with uow:
        events = uow.calendar.list_range(
            company_id=user.company_id,
            starts_at=starts_at,
            ends_at=ends_at,
            installer_id=installer_id,
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
