from __future__ import annotations

import uuid
from datetime import datetime

from app.shared.domain.errors import NotFound, ValidationError
from app.modules.calendar.domain.enums import CalendarEventType
from app.modules.calendar.infrastructure.models import CalendarEventORM


class CalendarUseCases:
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
    ) -> CalendarEventORM:
        if ends_at <= starts_at:
            raise ValidationError("ends_at must be after starts_at")

        location_final = location.strip() if location else None
        if project_id is not None:
            project = uow.projects.get(
                company_id=company_id,
                project_id=project_id,
            )
            if not project:
                raise NotFound(
                    "Project not found", details={"project_id": str(project_id)}
                )
            if not location_final:
                location_final = project.address

        e = CalendarEventORM(
            company_id=company_id,
            title=title,
            event_type=CalendarEventType(event_type),
            starts_at=starts_at,
            ends_at=ends_at,
            location=location_final,
            description=description,
            project_id=project_id,
        )
        uow.calendar.save_event(e)
        uow.session.flush()

        if installer_ids:
            uow.calendar.set_assignees(
                company_id=company_id,
                event_id=e.id,
                installer_ids=installer_ids,
            )

        return e

    @staticmethod
    def update_event(
        uow,
        *,
        company_id: uuid.UUID,
        event_id: uuid.UUID,
        **kwargs,
    ) -> CalendarEventORM:
        e = uow.calendar.get(company_id=company_id, event_id=event_id)
        if not e:
            raise NotFound(
                "Event not found", details={"event_id": str(event_id)}
            )

        for field in (
            "title",
            "event_type",
            "location",
            "description",
            "project_id",
            "starts_at",
            "ends_at",
        ):
            if field in kwargs and kwargs[field] is not None:
                val = kwargs[field]
                if field == "event_type":
                    val = CalendarEventType(val)
                if field == "location" and isinstance(val, str):
                    val = val.strip() or None
                setattr(e, field, val)

        if "project_id" in kwargs and kwargs["project_id"] is not None:
            project = uow.projects.get(
                company_id=company_id,
                project_id=kwargs["project_id"],
            )
            if not project:
                raise NotFound(
                    "Project not found",
                    details={"project_id": str(kwargs["project_id"])},
                )
            if "location" not in kwargs or kwargs["location"] is None:
                if not e.location:
                    e.location = project.address

        if e.ends_at <= e.starts_at:
            raise ValidationError("ends_at must be after starts_at")

        uow.calendar.save_event(e)

        if "installer_ids" in kwargs and kwargs["installer_ids"] is not None:
            uow.calendar.set_assignees(
                company_id=company_id,
                event_id=event_id,
                installer_ids=kwargs["installer_ids"],
            )

        return e

    @staticmethod
    def delete_event(
        uow,
        *,
        company_id: uuid.UUID,
        event_id: uuid.UUID,
    ) -> None:
        e = uow.calendar.get(company_id=company_id, event_id=event_id)
        if not e:
            raise NotFound(
                "Event not found", details={"event_id": str(event_id)}
            )
        uow.calendar.delete_event(e)
