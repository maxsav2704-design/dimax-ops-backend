from __future__ import annotations


class DashboardRepository:
    @staticmethod
    def compose_dashboard(*, sync_health: dict) -> dict:
        return {
            "sync_health": sync_health,
        }
