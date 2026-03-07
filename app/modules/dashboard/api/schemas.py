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


class DashboardLimitMetricDTO(BaseModel):
    current: int
    max: int | None
    utilization_pct: float | None
    is_enforced: bool
    is_exceeded: bool


class DashboardLimitsDTO(BaseModel):
    plan_code: str | None
    plan_active: bool | None
    total_doors: int
    users: DashboardLimitMetricDTO
    admin_users: DashboardLimitMetricDTO | None = None
    installer_users: DashboardLimitMetricDTO | None = None
    installers: DashboardLimitMetricDTO
    projects: DashboardLimitMetricDTO
    doors_per_project: DashboardLimitMetricDTO


class DashboardResponseDTO(BaseModel):
    sync_health: DashboardSyncHealthDTO
    limits: DashboardLimitsDTO
    limit_alerts_unread_count: int
