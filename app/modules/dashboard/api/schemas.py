from __future__ import annotations

from pydantic import BaseModel


class DashboardSyncHealthItemDTO(BaseModel):
    installer_id: str
    status: str
    lag: int
    days_offline: int
    last_seen_at: str | None


class DashboardSyncHealthCountsDTO(BaseModel):
    ok: int
    warn: int
    danger: int
    total: int
    dead: int
    never_seen: int
    danger_pct: float


class DashboardSyncHealthDTO(BaseModel):
    max_cursor: int
    counts: DashboardSyncHealthCountsDTO
    alerts_sent: int
    top_laggers: list[DashboardSyncHealthItemDTO]
    top_offline: list[DashboardSyncHealthItemDTO]


class DashboardResponseDTO(BaseModel):
    sync_health: DashboardSyncHealthDTO
