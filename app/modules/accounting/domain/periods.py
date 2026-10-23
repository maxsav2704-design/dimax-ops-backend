"""Accounting periods: from the 10th inclusive to the next 10th exclusive, Asia/Jerusalem (spec R12, R23).

The owner decided on 2026-10-23 that the new accounting starts on 10 November 2026, so the first
period is 10.11.2026 - 09.12.2026. Period boundaries are computed from the local calendar day, never
from a UTC offset fixed by hand, so daylight-saving changes do not move the boundary.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Jerusalem")
PERIOD_DAY = 10
CUTOVER = date(2026, 11, 10)


@dataclass(frozen=True)
class Period:
    start: date  # inclusive, always the 10th
    end_exclusive: date  # the next 10th

    @property
    def end(self) -> date:
        return self.end_exclusive - timedelta(days=1)

    @property
    def key(self) -> str:
        return self.start.isoformat()

    def contains(self, day: date) -> bool:
        return self.start <= day < self.end_exclusive


def _tenth(year: int, month: int) -> date:
    return date(year, month, PERIOD_DAY)


def _next_tenth(start: date) -> date:
    return _tenth(start.year + 1, 1) if start.month == 12 else _tenth(start.year, start.month + 1)


def _previous_tenth(start: date) -> date:
    return _tenth(start.year - 1, 12) if start.month == 1 else _tenth(start.year, start.month - 1)


def local_day(moment: datetime) -> date:
    """Calendar day of an aware moment in Asia/Jerusalem. Naive datetimes are refused: they hide the offset."""
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("period boundaries need a timezone-aware datetime")
    return moment.astimezone(TZ).date()


def period_for_day(day: date) -> Period:
    this_month = _tenth(day.year, day.month)
    start = this_month if day.day >= PERIOD_DAY else _previous_tenth(this_month)
    return Period(start, _next_tenth(start))


def period_for(moment: datetime) -> Period:
    return period_for_day(local_day(moment))


def period_from_key(key: str) -> Period:
    start = date.fromisoformat(key)
    if start.day != PERIOD_DAY:
        raise ValueError("a period starts on the 10th")
    return Period(start, _next_tenth(start))


def periods_between(first_day: date, last_day: date) -> list[Period]:
    """Every period touching [first_day, last_day], oldest first."""
    periods: list[Period] = []
    current = period_for_day(first_day)
    while current.start <= last_day:
        periods.append(current)
        current = Period(current.end_exclusive, _next_tenth(current.end_exclusive))
    return periods
