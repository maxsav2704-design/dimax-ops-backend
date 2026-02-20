from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import desc, func, nulls_last, or_
from sqlalchemy.orm import Session

from app.modules.doors.infrastructure.models import DoorORM
from app.modules.installers.infrastructure.models import InstallerORM
from app.modules.sync.domain.enums import SyncChangeType
from app.modules.sync.infrastructure.models import (
    InstallerSyncStateORM,
    SyncChangeLogORM,
    SyncEventORM,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SyncEventRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def exists_client_event(
        self, *, company_id: uuid.UUID, client_event_id: str
    ) -> bool:
        return (
            self.session.query(SyncEventORM.id)
            .filter(
                SyncEventORM.company_id == company_id,
                SyncEventORM.client_event_id == client_event_id,
            )
            .first()
            is not None
        )

    def create_pending(
        self,
        *,
        company_id: uuid.UUID,
        installer_id: uuid.UUID,
        project_id: uuid.UUID,
        event_type,
        client_event_id: str,
        client_happened_at: datetime | None,
        payload: dict,
    ) -> SyncEventORM:
        row = SyncEventORM(
            company_id=company_id,
            installer_id=installer_id,
            project_id=project_id,
            event_type=event_type,
            client_event_id=client_event_id,
            client_happened_at=client_happened_at,
            payload=payload,
            applied_at=None,
            apply_error=None,
        )
        self.session.add(row)
        return row

    def mark_applied(self, row: SyncEventORM) -> None:
        row.applied_at = utcnow()
        row.apply_error = None
        self.session.add(row)

    def mark_failed(self, row: SyncEventORM, *, error: str) -> None:
        row.applied_at = utcnow()
        row.apply_error = error[:5000]
        self.session.add(row)


class SyncChangeLogRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add_change(
        self,
        *,
        company_id: uuid.UUID,
        change_type: SyncChangeType,
        entity_id: uuid.UUID,
        project_id: uuid.UUID,
        installer_id: uuid.UUID | None,
        payload: dict,
    ) -> None:
        row = SyncChangeLogORM(
            company_id=company_id,
            created_at=utcnow(),
            change_type=change_type,
            entity_id=entity_id,
            project_id=project_id,
            installer_id=installer_id,
            payload=payload,
        )
        self.session.add(row)

    def pull_for_installer(
        self,
        *,
        company_id: uuid.UUID,
        installer_id: uuid.UUID,
        since_cursor: int,
        limit: int,
    ) -> list[SyncChangeLogORM]:
        # проекты, где у монтажника есть хотя бы одна дверь
        project_ids = [
            x[0]
            for x in (
                self.session.query(DoorORM.project_id)
                .filter(
                    DoorORM.company_id == company_id,
                    DoorORM.installer_id == installer_id,
                )
                .distinct()
                .all()
            )
        ]

        # если проектов нет — смысла тянуть "общие по проекту" тоже нет
        base_filter = [
            SyncChangeLogORM.company_id == company_id,
            SyncChangeLogORM.cursor_id > since_cursor,
        ]

        if project_ids:
            scope_filter = or_(
                SyncChangeLogORM.installer_id == installer_id,
                (
                    SyncChangeLogORM.installer_id.is_(None)
                    & SyncChangeLogORM.project_id.in_(project_ids)
                ),
            )
        else:
            scope_filter = SyncChangeLogORM.installer_id == installer_id

        q = (
            self.session.query(SyncChangeLogORM)
            .filter(*base_filter)
            .filter(scope_filter)
            .order_by(SyncChangeLogORM.cursor_id.asc())
            .limit(limit)
        )

        return q.all()

    def min_cursor(self, *, company_id: uuid.UUID) -> int | None:
        v = (
            self.session.query(func.min(SyncChangeLogORM.cursor_id))
            .filter(SyncChangeLogORM.company_id == company_id)
            .scalar()
        )
        return int(v) if v is not None else None

    def max_cursor(self, *, company_id: uuid.UUID) -> int:
        v = (
            self.session.query(func.max(SyncChangeLogORM.cursor_id))
            .filter(SyncChangeLogORM.company_id == company_id)
            .scalar()
        )
        return int(v) if v is not None else 0


class InstallerSyncStateRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_or_create(
        self, *, company_id: uuid.UUID, installer_id: uuid.UUID
    ) -> InstallerSyncStateORM:
        row = (
            self.session.query(InstallerSyncStateORM)
            .filter(
                InstallerSyncStateORM.company_id == company_id,
                InstallerSyncStateORM.installer_id == installer_id,
            )
            .one_or_none()
        )
        if not row:
            row = InstallerSyncStateORM(
                company_id=company_id,
                installer_id=installer_id,
                last_cursor_ack=0,
            )
            self.session.add(row)
        return row

    def ack_cursor(
        self,
        *,
        company_id: uuid.UUID,
        installer_id: uuid.UUID,
        cursor: int,
        app_version: str | None = None,
        device_id: str | None = None,
    ) -> None:
        row = self.get_or_create(
            company_id=company_id, installer_id=installer_id
        )

        if cursor > int(row.last_cursor_ack or 0):
            row.last_cursor_ack = cursor

        row.last_seen_at = utcnow()
        if app_version is not None:
            row.app_version = app_version
        if device_id is not None:
            row.device_id = device_id

        self.session.add(row)

    def min_ack_for_company(
        self, *, company_id: uuid.UUID, active_days: int
    ) -> int:
        cutoff = utcnow() - timedelta(days=active_days)
        v = (
            self.session.query(
                func.min(InstallerSyncStateORM.last_cursor_ack)
            )
            .filter(
                InstallerSyncStateORM.company_id == company_id,
                InstallerSyncStateORM.last_seen_at.isnot(None),
                InstallerSyncStateORM.last_seen_at >= cutoff,
            )
            .scalar()
        )
        return int(v or 0)

    def active_installers_count(self, *, company_id: uuid.UUID) -> int:
        return (
            self.session.query(InstallerSyncStateORM.id)
            .filter(InstallerSyncStateORM.company_id == company_id)
            .count()
        )

    def list_states(
        self, *, company_id: uuid.UUID
    ) -> list[InstallerSyncStateORM]:
        return (
            self.session.query(InstallerSyncStateORM)
            .filter(InstallerSyncStateORM.company_id == company_id)
            .order_by(desc(InstallerSyncStateORM.last_seen_at))
            .all()
        )

    def list_states_with_installers(
        self, *, company_id: uuid.UUID
    ) -> list[tuple[InstallerSyncStateORM, InstallerORM | None]]:
        rows = (
            self.session.query(InstallerSyncStateORM, InstallerORM)
            .join(
                InstallerORM,
                InstallerORM.id == InstallerSyncStateORM.installer_id,
                isouter=True,
            )
            .filter(InstallerSyncStateORM.company_id == company_id)
            .order_by(
                nulls_last(desc(InstallerSyncStateORM.last_seen_at))
            )
            .all()
        )
        return [(state, installer) for state, installer in rows]

    def list_states_for_health(
        self, *, company_id: uuid.UUID
    ) -> list[InstallerSyncStateORM]:
        return (
            self.session.query(InstallerSyncStateORM)
            .filter(InstallerSyncStateORM.company_id == company_id)
            .order_by(nulls_last(desc(InstallerSyncStateORM.last_seen_at)))
            .all()
        )

    def get_stats(self, *, company_id: uuid.UUID) -> dict:
        now = utcnow()
        active_threshold = now - timedelta(days=30)

        total = (
            self.session.query(func.count(InstallerSyncStateORM.installer_id))
            .filter(InstallerSyncStateORM.company_id == company_id)
            .scalar()
        )

        active = (
            self.session.query(func.count(InstallerSyncStateORM.installer_id))
            .filter(
                InstallerSyncStateORM.company_id == company_id,
                InstallerSyncStateORM.last_seen_at >= active_threshold,
            )
            .scalar()
        )

        return {
            "total_installers": total or 0,
            "active_last_30_days": active or 0,
        }

    def reset_installer(
        self, *, company_id: uuid.UUID, installer_id: uuid.UUID
    ) -> bool:
        row = (
            self.session.query(InstallerSyncStateORM)
            .filter(
                InstallerSyncStateORM.company_id == company_id,
                InstallerSyncStateORM.installer_id == installer_id,
            )
            .first()
        )

        if not row:
            return False

        row.last_cursor_ack = 0
        row.last_seen_at = None
        return True

    def reset_installer_to_initial(
        self, *, company_id: uuid.UUID, installer_id: uuid.UUID
    ) -> InstallerSyncStateORM:
        row = self.get_or_create(
            company_id=company_id, installer_id=installer_id
        )
        row.last_cursor_ack = 0
        row.last_seen_at = None
        row.health_status = "UNKNOWN"
        row.health_days_offline = 0
        row.health_lag = None
        row.last_alert_at = None
        row.last_alert_lag = None
        row.app_version = None
        row.device_id = None
        self.session.flush()
        return row


class SyncChangeLogGCRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def delete_upto_cursor(
        self, *, company_id: uuid.UUID, max_cursor_inclusive: int
    ) -> int:
        q = self.session.query(SyncChangeLogORM).filter(
            SyncChangeLogORM.company_id == company_id,
            SyncChangeLogORM.cursor_id <= max_cursor_inclusive,
        )
        deleted = q.delete(synchronize_session=False)
        return int(deleted)
