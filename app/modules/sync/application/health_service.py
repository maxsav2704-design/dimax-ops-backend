from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from app.core.config import settings

# System actor for auto-actions (audit log)
SYSTEM_ACTOR_ID = uuid.UUID("00000000-0000-0000-0000-000000000000")


@dataclass
class HealthResult:
    installer_id: str
    status: str
    lag: int
    days_offline: int
    last_seen_at: str | None


class SyncHealthService:
    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _days_offline(last_seen_at: datetime | None) -> int:
        if not last_seen_at:
            return 999999
        now = SyncHealthService._utcnow()
        if last_seen_at.tzinfo is None:
            from datetime import timezone as tz
            last_seen_at = last_seen_at.replace(tzinfo=tz.utc)
        delta = now - last_seen_at
        return max(0, int(delta.total_seconds() // 86400))

    @staticmethod
    def _status(lag: int, days_offline: int) -> str:
        if (
            lag >= settings.SYNC_DANGER_LAG
            or days_offline >= settings.SYNC_DANGER_DAYS_OFFLINE
        ):
            return "DANGER"
        if (
            lag >= settings.SYNC_WARN_LAG
            or days_offline >= settings.SYNC_WARN_DAYS_OFFLINE
        ):
            return "WARN"
        return "OK"

    @staticmethod
    def run_for_company(uow, *, company_id) -> dict:
        now = SyncHealthService._utcnow()
        max_cursor = uow.sync_change_log.max_cursor(company_id=company_id)

        rows = uow.sync_state.list_states_for_health(company_id=company_id)

        results: list[HealthResult] = []
        danger_items = []
        warn_items = []
        ok_count = 0

        for r in rows:
            last_ack = int(r.last_cursor_ack or 0)
            lag = max(0, int(max_cursor - last_ack))
            days_offline = SyncHealthService._days_offline(r.last_seen_at)
            status = SyncHealthService._status(lag, days_offline)

            r.health_status = status
            r.health_lag = lag
            r.health_days_offline = days_offline

            results.append(
                HealthResult(
                    installer_id=str(r.installer_id),
                    status=status,
                    lag=lag,
                    days_offline=days_offline,
                    last_seen_at=(
                        r.last_seen_at.isoformat() if r.last_seen_at else None
                    ),
                )
            )

            if status == "DANGER":
                danger_items.append(r)
            elif status == "WARN":
                warn_items.append(r)
            else:
                ok_count += 1

        alerts_sent = 0
        if settings.SYNC_ALERT_WEBHOOK_URL:
            for r in danger_items:
                if SyncHealthService._should_alert(r, now):
                    installer = uow.installers.get(
                        company_id=company_id, installer_id=r.installer_id
                    )
                    SyncHealthService._send_webhook_alert(
                        company_id=str(company_id),
                        installer_id=str(r.installer_id),
                        lag=int(r.health_lag or 0),
                        days_offline=int(r.health_days_offline or 0),
                        last_seen_at=(
                            r.last_seen_at.isoformat()
                            if r.last_seen_at
                            else None
                        ),
                        max_cursor=int(max_cursor),
                        installer_name=installer.full_name if installer else None,
                        installer_phone=installer.phone if installer else None,
                    )
                    r.last_alert_at = now
                    r.last_alert_lag = int(r.health_lag or 0)
                    alerts_sent += 1

        uow.session.flush()

        top_laggers = sorted(results, key=lambda x: x.lag, reverse=True)[:5]
        top_offline = sorted(
            results, key=lambda x: x.days_offline, reverse=True
        )[:5]

        danger_pct = 0.0
        total = len(results)
        if total:
            danger_pct = round((len(danger_items) / total) * 100.0, 2)

        dead_count = sum(
            1
            for x in results
            if x.days_offline >= settings.SYNC_DANGER_DAYS_OFFLINE
        )
        never_seen = sum(1 for x in results if x.last_seen_at is None)

        if settings.SYNC_PROJECT_AUTO_PROBLEM_ENABLED:
            SyncHealthService._auto_mark_projects_problem(
                uow, company_id=company_id
            )
        else:
            danger_installer_ids = [
                r.installer_id
                for r in danger_items
                if (r.health_days_offline or 0)
                >= settings.SYNC_PROJECT_AUTO_PROBLEM_DAYS
            ]
            ok_installer_ids = [
                r.installer_id for r in rows if r.installer_id not in danger_installer_ids
            ]
            SyncHealthService._create_or_close_sync_risk_issues(
                uow,
                company_id=company_id,
                danger_installer_ids=danger_installer_ids,
                ok_installer_ids=ok_installer_ids,
            )

        return {
            "max_cursor": int(max_cursor),
            "counts": {
                "ok": ok_count,
                "warn": len(warn_items),
                "danger": len(danger_items),
                "total": total,
                "dead": dead_count,
                "never_seen": never_seen,
                "danger_pct": danger_pct,
            },
            "alerts_sent": alerts_sent,
            "top_laggers": [x.__dict__ for x in top_laggers],
            "top_offline": [x.__dict__ for x in top_offline],
        }

    @staticmethod
    def _should_alert(state_row, now: datetime) -> bool:
        cooldown_sec = settings.SYNC_ALERT_COOLDOWN_MINUTES * 60
        last = state_row.last_alert_at
        if not last:
            return True
        if last.tzinfo is None:
            from datetime import timezone as tz
            last = last.replace(tzinfo=tz.utc)
        return (now - last).total_seconds() >= cooldown_sec

    @staticmethod
    def _send_webhook_alert(
        *,
        company_id: str,
        installer_id: str,
        lag: int,
        days_offline: int,
        last_seen_at: str | None,
        max_cursor: int,
        installer_name: str | None = None,
        installer_phone: str | None = None,
    ) -> None:
        payload = {
            "type": "SYNC_DANGER",
            "company_id": company_id,
            "installer_id": installer_id,
            "lag": lag,
            "days_offline": days_offline,
            "last_seen_at": last_seen_at,
            "max_cursor": max_cursor,
            "ts": SyncHealthService._utcnow().isoformat(),
        }
        if installer_name is not None:
            payload["installer_name"] = installer_name
        if installer_phone is not None:
            payload["installer_phone"] = installer_phone
        try:
            httpx.post(
                settings.SYNC_ALERT_WEBHOOK_URL,
                json=payload,
                timeout=5.0,
            )
        except Exception:
            pass

    @staticmethod
    def _create_or_close_sync_risk_issues(
        uow,
        *,
        company_id: uuid.UUID,
        danger_installer_ids: list[uuid.UUID],
        ok_installer_ids: list[uuid.UUID],
    ) -> None:
        danger_project_ids = (
            uow.doors.find_project_ids_by_installers(
                company_id=company_id,
                installer_ids=danger_installer_ids,
            )
            if danger_installer_ids
            else []
        )
        ok_project_ids = (
            uow.doors.find_project_ids_by_installers(
                company_id=company_id,
                installer_ids=ok_installer_ids,
            )
            if ok_installer_ids
            else []
        )
        for pid in danger_project_ids:
            uow.issues.upsert_sync_risk(
                company_id=company_id,
                project_id=pid,
            )
        for pid in ok_project_ids:
            uow.issues.close_sync_risk(
                company_id=company_id,
                project_id=pid,
            )

    @staticmethod
    def _auto_mark_projects_problem(uow, *, company_id: uuid.UUID) -> None:
        from app.modules.audit.infrastructure.models import AuditLogORM

        rows = uow.sync_state.list_states_for_health(company_id=company_id)
        danger_installers = [
            r.installer_id
            for r in rows
            if r.health_status == "DANGER"
            and (r.health_days_offline or 0)
            >= settings.SYNC_PROJECT_AUTO_PROBLEM_DAYS
        ]
        if not danger_installers:
            return

        project_ids = uow.doors.find_project_ids_by_installers(
            company_id=company_id,
            installer_ids=danger_installers,
        )
        updated = uow.projects.mark_problem_bulk(
            company_id=company_id,
            project_ids=project_ids,
            reason="SYNC_DANGER_AUTO",
        )

        for pid in updated:
            uow.audit.add(
                AuditLogORM(
                    company_id=company_id,
                    actor_user_id=SYSTEM_ACTOR_ID,
                    entity_type="project",
                    entity_id=pid,
                    action="PROJECT_AUTO_PROBLEM",
                    reason="SYNC_DANGER_AUTO",
                    after={
                        "reason": "SYNC_DANGER_AUTO",
                        "days": settings.SYNC_PROJECT_AUTO_PROBLEM_DAYS,
                    },
                )
            )
