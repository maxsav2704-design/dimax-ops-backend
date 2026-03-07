from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import httpx

from app.core.config import settings
from app.modules.audit.application.service import AuditService

SYSTEM_ACTOR_ID = uuid.UUID("00000000-0000-0000-0000-000000000000")

_METRIC_KEYS: tuple[str, ...] = (
    "users",
    "installers",
    "projects",
    "doors_per_project",
)


class CompanyLimitAlertsService:
    @staticmethod
    def evaluate_and_alert(
        uow,
        *,
        company_id: uuid.UUID,
        actor_user_id: uuid.UUID | None = None,
        metric_keys: list[str] | None = None,
    ) -> None:
        plans_repo = getattr(uow, "company_plans", None)
        audit_repo = getattr(uow, "audit", None)
        if plans_repo is None or audit_repo is None:
            return
        limits = plans_repo.limits_kpi(company_id)
        selected = tuple(metric_keys or _METRIC_KEYS)

        for metric_key in selected:
            metric = limits.get(metric_key)
            if not isinstance(metric, dict):
                continue
            if not metric.get("is_enforced"):
                continue
            utilization_pct = metric.get("utilization_pct")
            if utilization_pct is None:
                continue

            level = CompanyLimitAlertsService._level_from_utilization(float(utilization_pct))
            if level is None:
                continue

            action = CompanyLimitAlertsService._action(metric_key=metric_key, level=level)
            if CompanyLimitAlertsService._is_in_cooldown(
                uow,
                company_id=company_id,
                action=action,
            ):
                continue

            payload = {
                "metric": metric_key,
                "level": level,
                "current": metric.get("current"),
                "max": metric.get("max"),
                "utilization_pct": utilization_pct,
                "plan_code": limits.get("plan_code"),
            }
            AuditService.add(
                uow,
                company_id=company_id,
                actor_user_id=actor_user_id or SYSTEM_ACTOR_ID,
                entity_type="company_plan",
                entity_id=company_id,
                action=action,
                before=None,
                after=payload,
            )
            CompanyLimitAlertsService._send_webhook_alert(
                company_id=company_id,
                action=action,
                payload=payload,
            )

    @staticmethod
    def _level_from_utilization(utilization_pct: float) -> str | None:
        if utilization_pct >= float(settings.PLAN_ALERT_DANGER_PCT):
            return "DANGER"
        if utilization_pct >= float(settings.PLAN_ALERT_WARN_PCT):
            return "WARN"
        return None

    @staticmethod
    def _action(*, metric_key: str, level: str) -> str:
        return f"PLAN_LIMIT_ALERT_{level}_{metric_key.upper()}"

    @staticmethod
    def _is_in_cooldown(
        uow,
        *,
        company_id: uuid.UUID,
        action: str,
    ) -> bool:
        now = datetime.now(timezone.utc)
        since = now - timedelta(minutes=int(settings.PLAN_ALERT_COOLDOWN_MINUTES))
        return uow.audit.exists_recent_action(
            company_id=company_id,
            action=action,
            since=since,
        )

    @staticmethod
    def _send_webhook_alert(
        *,
        company_id: uuid.UUID,
        action: str,
        payload: dict,
    ) -> None:
        webhook = settings.PLAN_ALERT_WEBHOOK_URL
        if not webhook:
            return
        body = {
            "type": "PLAN_LIMIT_ALERT",
            "action": action,
            "company_id": str(company_id),
            "ts": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
        }
        try:
            httpx.post(webhook, json=body, timeout=5.0)
        except Exception:
            pass
