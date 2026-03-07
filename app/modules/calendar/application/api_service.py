from __future__ import annotations

import uuid
from datetime import datetime

from app.modules.calendar.api.schemas import (
    EventCreateResponse,
    EventDTO,
    EventListResponse,
)
from app.modules.calendar.application.use_cases import CalendarUseCases
from app.shared.application.navigation import build_waze_url


def _event_type_value(e) -> str:
    return e.event_type.value if hasattr(e.event_type, "value") else str(e.event_type)


class CalendarApiService:
    @staticmethod
    def list_events(
        uow,
        *,
        company_id: uuid.UUID,
        starts_at: datetime,
        ends_at: datetime,
        installer_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
        event_type: str | None = None,
    ) -> EventListResponse:
        events = uow.calendar.list_range(
            company_id=company_id,
            starts_at=starts_at,
            ends_at=ends_at,
            installer_id=installer_id,
            project_id=project_id,
            event_type=event_type,
        )
        items: list[EventDTO] = []
        project_addresses: dict[uuid.UUID, str | None] = {}
        for e in events:
            assignees = uow.calendar.get_assignee_ids(
                company_id=company_id, event_id=e.id
            )
            navigation_address = e.location
            if (not navigation_address) and e.project_id:
                if e.project_id not in project_addresses:
                    project = uow.projects.get(
                        company_id=company_id,
                        project_id=e.project_id,
                    )
                    project_addresses[e.project_id] = (
                        project.address if project else None
                    )
                navigation_address = project_addresses[e.project_id]
            items.append(
                EventDTO(
                    id=e.id,
                    title=e.title,
                    event_type=_event_type_value(e),
                    starts_at=e.starts_at,
                    ends_at=e.ends_at,
                    location=e.location,
                    waze_url=build_waze_url(address=navigation_address),
                    description=e.description,
                    project_id=e.project_id,
                    installer_ids=assignees,
                )
            )
        return EventListResponse(items=items)

    @staticmethod
    def create_event(
        uow,
        *,
        company_id: uuid.UUID,
        title: str,
        event_type: str,
        starts_at: datetime,
        ends_at: datetime,
        location: str | None,
        description: str | None,
        project_id: uuid.UUID | None,
        installer_ids: list[uuid.UUID],
    ) -> EventCreateResponse:
        e = CalendarUseCases.create_event(
            uow,
            company_id=company_id,
            title=title,
            event_type=event_type,
            starts_at=starts_at,
            ends_at=ends_at,
            location=location,
            description=description,
            project_id=project_id,
            installer_ids=list(installer_ids),
        )
        return EventCreateResponse(id=e.id)

    @staticmethod
    def update_event(
        uow,
        *,
        company_id: uuid.UUID,
        event_id: uuid.UUID,
        payload: dict,
    ) -> None:
        if "installer_ids" in payload and payload["installer_ids"] is not None:
            payload["installer_ids"] = list(payload["installer_ids"])
        CalendarUseCases.update_event(
            uow,
            company_id=company_id,
            event_id=event_id,
            **payload,
        )

    @staticmethod
    def delete_event(
        uow,
        *,
        company_id: uuid.UUID,
        event_id: uuid.UUID,
    ) -> None:
        CalendarUseCases.delete_event(
            uow,
            company_id=company_id,
            event_id=event_id,
        )
