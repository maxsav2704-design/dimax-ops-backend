from __future__ import annotations

from app.modules.audit.application.service import AuditService
from app.modules.identity.domain.enums import UserRole
from app.modules.sync.infrastructure.repositories import InstallerSyncStateRepository


def _dt(value) -> str | None:
    return value.isoformat() if value else None


def _sync_state_snapshot(state, *, installer=None, user_id=None) -> dict | None:
    if state is None:
        return None
    return {
        "installer_id": str(state.installer_id),
        "installer_name": installer.full_name if installer else None,
        "installer_phone": installer.phone if installer else None,
        "user_id": str(user_id) if user_id else None,
        "last_cursor_ack": int(state.last_cursor_ack or 0),
        "last_seen_at": _dt(state.last_seen_at),
        "app_version": state.app_version,
        "device_id": state.device_id,
        "health_status": getattr(state, "health_status", None),
        "health_lag": getattr(state, "health_lag", None),
        "health_days_offline": getattr(state, "health_days_offline", None),
        "last_alert_at": _dt(getattr(state, "last_alert_at", None)),
        "last_alert_lag": getattr(state, "last_alert_lag", None),
    }


def _problem_code(*, status: str | None, conflict_code: str | None, error: str | None) -> str | None:
    raw_error = (error or "").strip()
    if conflict_code:
        return conflict_code
    if raw_error in {
        "CONFLICT_ASSIGNMENT_CHANGED",
        "CONFLICT_INVALID_TRANSITION",
        "AUTH_REQUIRED",
    }:
        return raw_error

    normalized = raw_error.lower()
    if status == "AUTH_REQUIRED" or "auth" in normalized:
        return "AUTH_REQUIRED"
    if "not assigned" in normalized or "assignment" in normalized:
        return "CONFLICT_ASSIGNMENT_CHANGED"
    if "invalid transition" in normalized or "stale" in normalized or "locked" in normalized:
        return "CONFLICT_INVALID_TRANSITION"
    if status == "PENDING":
        return "SYNC_PENDING"
    if status == "BLOCKED":
        return "SYNC_BLOCKED"
    if status == "FAILED":
        return "SYNC_APPLY_FAILED"
    return None


def _problem_resolution(*, status: str, conflict_code: str | None, error: str | None) -> dict:
    code = _problem_code(status=status, conflict_code=conflict_code, error=error)
    if code == "CONFLICT_ASSIGNMENT_CHANGED":
        return {
            "problem_code": code,
            "problem_title": "Assignment changed",
            "operator_action": (
                "Verify the current installer assignment, then request cold resync if the work still belongs "
                "to this installer. Do not retry the stale event blindly."
            ),
            "retry_allowed": False,
            "manual_review_required": True,
        }
    if code == "CONFLICT_INVALID_TRANSITION":
        return {
            "problem_code": code,
            "problem_title": "Door status is stale",
            "operator_action": (
                "Refresh installer data and confirm the current door status before asking the installer to "
                "record the next allowed action."
            ),
            "retry_allowed": False,
            "manual_review_required": True,
        }
    if code == "AUTH_REQUIRED":
        return {
            "problem_code": code,
            "problem_title": "Installer must sign in again",
            "operator_action": "Ask the installer to sign in again before sync can continue.",
            "retry_allowed": False,
            "manual_review_required": False,
        }
    if code == "SYNC_PENDING":
        return {
            "problem_code": code,
            "problem_title": "Waiting for sync",
            "operator_action": "Monitor connectivity and device activity; no office recovery action is needed yet.",
            "retry_allowed": True,
            "manual_review_required": False,
        }
    if code == "SYNC_BLOCKED":
        return {
            "problem_code": code,
            "problem_title": "Manual sync review needed",
            "operator_action": "Review the event payload and installer context before any retry or cleanup.",
            "retry_allowed": False,
            "manual_review_required": True,
        }
    return {
        "problem_code": code,
        "problem_title": "Sync apply failed",
        "operator_action": "Review the error and payload before deciding whether to reset sync state.",
        "retry_allowed": False,
        "manual_review_required": True,
    }


def _normalize_problem_status_filter(value: str | None) -> str:
    normalized = (value or "all").strip().lower()
    if normalized in {"failed", "conflict", "pending", "auth_required"}:
        return normalized
    return "all"


def _include_failed_events(status_filter: str) -> bool:
    return status_filter in {"all", "failed"}


def _queue_statuses_for_filter(status_filter: str) -> tuple[str, ...]:
    if status_filter == "conflict":
        return ("CONFLICT",)
    if status_filter == "pending":
        return ("PENDING", "BLOCKED")
    if status_filter == "auth_required":
        return ("AUTH_REQUIRED",)
    if status_filter == "failed":
        return ()
    return ("PENDING", "CONFLICT", "BLOCKED", "AUTH_REQUIRED")


class AdminSyncStateService:
    @staticmethod
    def list_problems(
        uow,
        *,
        company_id,
        limit: int = 25,
        installer_id=None,
        status_filter: str | None = None,
    ) -> dict:
        bounded_limit = max(1, min(int(limit or 25), 100))
        normalized_status_filter = _normalize_problem_status_filter(status_filter)
        include_failed_events = _include_failed_events(normalized_status_filter)
        queue_statuses = _queue_statuses_for_filter(normalized_status_filter)
        events = (
            uow.sync_events.list_failed_with_installers(
                company_id=company_id,
                installer_id=installer_id,
                limit=bounded_limit,
            )
            if include_failed_events
            else []
        )
        queue_items = (
            uow.sync_queue.list_problem_items_with_installers(
                company_id=company_id,
                installer_id=installer_id,
                limit=bounded_limit,
                statuses=queue_statuses,
            )
            if queue_statuses
            else []
        )
        total = (
            uow.sync_events.count_failed(
                company_id=company_id,
                installer_id=installer_id,
            )
            if include_failed_events
            else 0
        ) + (
            uow.sync_queue.count_problem_items(
                company_id=company_id,
                installer_id=installer_id,
                statuses=queue_statuses,
            )
            if queue_statuses
            else 0
        )

        items = []
        for event, installer in events:
            resolution = _problem_resolution(
                status="FAILED",
                conflict_code=None,
                error=event.apply_error,
            )
            items.append(
                {
                    "id": str(event.id),
                    "source": "sync_event",
                    "installer_id": str(event.installer_id),
                    "installer_name": installer.full_name if installer else None,
                    "installer_phone": installer.phone if installer else None,
                    "user_id": str(installer.user_id) if installer and installer.user_id else None,
                    "project_id": str(event.project_id),
                    "client_event_id": event.client_event_id,
                    "event_type": event.event_type.value,
                    "entity_type": None,
                    "entity_id": None,
                    "operation_type": None,
                    "status": "FAILED",
                    "conflict_code": None,
                    "error": event.apply_error,
                    **resolution,
                    "device_id": None,
                    "base_version": None,
                    "payload": event.payload or {},
                    "created_at": event.created_at,
                    "client_happened_at": event.client_happened_at,
                    "applied_at": event.applied_at,
                    "synced_at": None,
                }
            )

        for row, installer in queue_items:
            resolution = _problem_resolution(
                status=row.status,
                conflict_code=row.conflict_code,
                error=row.conflict_code,
            )
            items.append(
                {
                    "id": str(row.id),
                    "source": "sync_queue",
                    "installer_id": str(installer.id) if installer else None,
                    "installer_name": installer.full_name if installer else None,
                    "installer_phone": installer.phone if installer else None,
                    "user_id": str(row.user_id),
                    "project_id": str(row.project_id) if row.project_id else None,
                    "client_event_id": None,
                    "event_type": None,
                    "entity_type": row.entity_type,
                    "entity_id": str(row.entity_id),
                    "operation_type": row.operation_type,
                    "status": row.status,
                    "conflict_code": row.conflict_code,
                    "error": row.conflict_code,
                    **resolution,
                    "device_id": row.device_id,
                    "base_version": row.base_version,
                    "payload": row.payload or {},
                    "created_at": row.created_at,
                    "client_happened_at": None,
                    "applied_at": None,
                    "synced_at": row.synced_at,
                }
            )

        items.sort(
            key=lambda item: (
                item["applied_at"] or item["created_at"],
                item["id"],
            ),
            reverse=True,
        )
        visible = items[:bounded_limit]
        return {
            "items": visible,
            "total": total,
        }

    @staticmethod
    def list_states(uow, *, company_id) -> list[dict]:
        rows = uow.sync_state.list_states_with_installers(company_id=company_id)
        max_cursor = uow.sync_change_log.max_cursor(company_id=company_id)

        result = []
        for state, installer in rows:
            last_ack = int(state.last_cursor_ack or 0)
            lag = max(0, int(max_cursor - last_ack))

            result.append({
                "installer_id": str(state.installer_id),
                "installer_name": installer.full_name if installer else None,
                "installer_phone": installer.phone if installer else None,
                "installer_active": bool(installer.is_active) if installer else None,

                "last_cursor_ack": state.last_cursor_ack,
                "last_seen_at": state.last_seen_at,
                "lag": lag,

                "health_status": getattr(state, "health_status", None),
                "health_days_offline": getattr(state, "health_days_offline", None),
                "last_alert_at": getattr(state, "last_alert_at", None),
            })
        return result

    @staticmethod
    def get_stats(uow, *, company_id) -> dict:
        return uow.sync_state.get_stats(company_id=company_id)

    @staticmethod
    def reset_installer(uow, *, company_id, installer_id, actor_user_id=None) -> bool:
        installer = uow.installers.get(company_id, installer_id)
        before_state = uow.sync_state.get(
            company_id=company_id,
            installer_id=installer_id,
        )
        before = _sync_state_snapshot(
            before_state,
            installer=installer,
            user_id=installer.user_id if installer else None,
        )
        ok = uow.sync_state.reset_installer(
            company_id=company_id,
            installer_id=installer_id,
        )
        if ok and actor_user_id is not None:
            after_state = uow.sync_state.get(
                company_id=company_id,
                installer_id=installer_id,
            )
            AuditService.add(
                uow,
                company_id=company_id,
                actor_user_id=actor_user_id,
                entity_type="sync_state",
                entity_id=installer_id,
                action="SYNC_STATE_RESET",
                reason="admin_legacy_reset",
                before=before,
                after=_sync_state_snapshot(
                    after_state,
                    installer=installer,
                    user_id=installer.user_id if installer else None,
                ),
            )
        return ok

    @staticmethod
    def reset_sync_state(uow, *, company_id, user_id, actor_user_id=None) -> dict | None:
        """Reset sync state for installer (user with role INSTALLER). Returns SyncStateDTO-like dict or None if not found/not installer."""
        user = uow.users.get_by_id(company_id=company_id, user_id=user_id)
        if not user or user.role != UserRole.INSTALLER:
            return None
        installer = uow.installers.get_by_user_id(
            company_id=company_id, user_id=user_id
        )
        if not installer:
            return None
        before_state = uow.sync_state.get(
            company_id=company_id,
            installer_id=installer.id,
        )
        before = _sync_state_snapshot(
            before_state,
            installer=installer,
            user_id=user_id,
        )
        state = uow.sync_state.reset_installer_to_initial(
            company_id=company_id, installer_id=installer.id
        )
        if actor_user_id is not None:
            AuditService.add(
                uow,
                company_id=company_id,
                actor_user_id=actor_user_id,
                entity_type="sync_state",
                entity_id=installer.id,
                action="SYNC_STATE_RESET",
                reason="admin_cold_resync",
                before=before,
                after=_sync_state_snapshot(
                    state,
                    installer=installer,
                    user_id=user_id,
                ),
            )
        max_cursor = uow.sync_change_log.max_cursor(company_id=company_id)
        lag = max(0, int(max_cursor - (state.last_cursor_ack or 0)))
        return {
            "installer_id": str(state.installer_id),
            "installer_name": installer.full_name,
            "installer_phone": installer.phone,
            "installer_active": bool(installer.is_active),
            "last_cursor_ack": state.last_cursor_ack,
            "last_seen_at": state.last_seen_at,
            "lag": lag,
            "health_status": getattr(state, "health_status", None),
            "health_days_offline": getattr(state, "health_days_offline", None),
            "last_alert_at": getattr(state, "last_alert_at", None),
        }
