from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class SyncStateDTO(BaseModel):
    installer_id: str
    installer_name: str | None = None
    installer_phone: str | None = None
    installer_active: bool | None = None

    last_cursor_ack: int | None = None
    last_seen_at: datetime | None = None
    lag: int

    health_status: str | None = None
    health_days_offline: int | None = None
    last_alert_at: datetime | None = None


class SyncStatsDTO(BaseModel):
    total_installers: int
    active_last_30_days: int


class SyncProblemItemDTO(BaseModel):
    id: str
    source: str
    installer_id: str | None = None
    installer_name: str | None = None
    installer_phone: str | None = None
    user_id: str | None = None
    project_id: str | None = None
    client_event_id: str | None = None
    event_type: str | None = None
    entity_type: str | None = None
    entity_id: str | None = None
    operation_type: str | None = None
    status: str
    conflict_code: str | None = None
    error: str | None = None
    problem_code: str | None = None
    problem_title: str | None = None
    operator_action: str | None = None
    retry_allowed: bool = False
    manual_review_required: bool = True
    device_id: str | None = None
    base_version: int | None = None
    payload: dict
    created_at: datetime
    client_happened_at: datetime | None = None
    applied_at: datetime | None = None
    synced_at: datetime | None = None


class SyncProblemsResponseDTO(BaseModel):
    items: list[SyncProblemItemDTO]
    total: int


class SyncResetLegacyResponse(BaseModel):
    status: str


class SyncHealthItemDTO(BaseModel):
    installer_id: str
    installer_name: str | None = None
    installer_phone: str | None = None
    status: str
    lag: int
    days_offline: int
    last_seen_at: str | None = None
    failed_events: int = 0
    queue_pending: int = 0
    queue_conflicts: int = 0
    queue_blocked: int = 0
    queue_auth_required: int = 0
    problem_count: int = 0


class SyncHealthCountsDTO(BaseModel):
    ok: int
    warn: int
    danger: int
    total: int
    dead: int
    never_seen: int
    danger_pct: float
    failed_events: int = 0
    queue_pending: int = 0
    queue_conflicts: int = 0
    queue_blocked: int = 0
    queue_auth_required: int = 0
    problem_total: int = 0


class SyncHealthSummaryDTO(BaseModel):
    max_cursor: int
    counts: SyncHealthCountsDTO
    alerts_sent: int
    top_laggers: list[SyncHealthItemDTO]
    top_offline: list[SyncHealthItemDTO]


class SyncHealthRunResponseDTO(BaseModel):
    ok: bool
    data: SyncHealthSummaryDTO
