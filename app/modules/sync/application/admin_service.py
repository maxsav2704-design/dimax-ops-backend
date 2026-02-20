from __future__ import annotations

from app.modules.identity.domain.enums import UserRole
from app.modules.sync.infrastructure.repositories import InstallerSyncStateRepository


class AdminSyncStateService:
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
    def reset_installer(uow, *, company_id, installer_id) -> bool:
        return uow.sync_state.reset_installer(
            company_id=company_id,
            installer_id=installer_id,
        )

    @staticmethod
    def reset_sync_state(uow, *, company_id, user_id) -> dict | None:
        """Reset sync state for installer (user with role INSTALLER). Returns SyncStateDTO-like dict or None if not found/not installer."""
        user = uow.users.get_by_id(company_id=company_id, user_id=user_id)
        if not user or user.role != UserRole.INSTALLER:
            return None
        installer = uow.installers.get_by_user_id(
            company_id=company_id, user_id=user_id
        )
        if not installer:
            return None
        state = uow.sync_state.reset_installer_to_initial(
            company_id=company_id, installer_id=installer.id
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
