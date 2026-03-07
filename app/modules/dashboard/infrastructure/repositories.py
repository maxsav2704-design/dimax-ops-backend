from __future__ import annotations


class DashboardRepository:
    @staticmethod
    def compose_dashboard(
        *,
        sync_health: dict,
        limits: dict,
        limit_alerts_unread_count: int,
    ) -> dict:
        return {
            "sync_health": sync_health,
            "limits": limits,
            "limit_alerts_unread_count": int(limit_alerts_unread_count),
        }
