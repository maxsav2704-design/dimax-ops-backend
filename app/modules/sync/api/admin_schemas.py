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
