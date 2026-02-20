from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.modules.calendar.infrastructure.models import (
    CalendarEventAssigneeORM,
    CalendarEventORM,
)


class CalendarRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(
        self, *, company_id: uuid.UUID, event_id: uuid.UUID
    ) -> CalendarEventORM | None:
        return (
            self.session.query(CalendarEventORM)
            .filter(
                CalendarEventORM.company_id == company_id,
                CalendarEventORM.id == event_id,
            )
            .one_or_none()
        )

    def list_range(
        self,
        *,
        company_id: uuid.UUID,
        starts_at: datetime,
        ends_at: datetime,
        installer_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
        event_type: str | None = None,
        limit: int = 500,
    ) -> list[CalendarEventORM]:
        q = (
            self.session.query(CalendarEventORM)
            .filter(
                CalendarEventORM.company_id == company_id,
                CalendarEventORM.starts_at < ends_at,
                CalendarEventORM.ends_at > starts_at,
            )
        )
        if project_id:
            q = q.filter(CalendarEventORM.project_id == project_id)
        if event_type:
            q = q.filter(CalendarEventORM.event_type == event_type)

        if installer_id:
            q = q.join(
                CalendarEventAssigneeORM,
                CalendarEventAssigneeORM.event_id == CalendarEventORM.id,
            ).filter(
                CalendarEventAssigneeORM.company_id == company_id,
                CalendarEventAssigneeORM.installer_id == installer_id,
            )

        return q.order_by(CalendarEventORM.starts_at.asc()).limit(limit).all()

    def save_event(self, event: CalendarEventORM) -> None:
        self.session.add(event)

    def delete_event(self, event: CalendarEventORM) -> None:
        self.session.delete(event)

    def set_assignees(
        self,
        *,
        company_id: uuid.UUID,
        event_id: uuid.UUID,
        installer_ids: list[uuid.UUID],
    ) -> None:
        self.session.query(CalendarEventAssigneeORM).filter(
            CalendarEventAssigneeORM.company_id == company_id,
            CalendarEventAssigneeORM.event_id == event_id,
        ).delete(synchronize_session=False)

        rows = [
            CalendarEventAssigneeORM(
                company_id=company_id,
                event_id=event_id,
                installer_id=i,
            )
            for i in installer_ids
        ]
        self.session.add_all(rows)

    def get_assignee_ids(
        self, *, company_id: uuid.UUID, event_id: uuid.UUID
    ) -> list[uuid.UUID]:
        rows = (
            self.session.query(CalendarEventAssigneeORM.installer_id)
            .filter(
                CalendarEventAssigneeORM.company_id == company_id,
                CalendarEventAssigneeORM.event_id == event_id,
            )
            .all()
        )
        return [r[0] for r in rows]
