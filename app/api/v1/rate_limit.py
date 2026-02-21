from __future__ import annotations

import time
from collections import deque
from typing import Deque, Dict

from fastapi import Request

from app.core.config import settings
from app.shared.domain.errors import Forbidden

_BUCKETS: Dict[str, Deque[float]] = {}


def _allow(key: str, *, window: int, max_req: int) -> None:
    now = time.time()

    dq = _BUCKETS.get(key)
    if dq is None:
        dq = deque()
        _BUCKETS[key] = dq

    while dq and dq[0] <= now - window:
        dq.popleft()

    if len(dq) >= max_req:
        raise Forbidden("Too many requests. Slow down.")

    dq.append(now)


def rate_limit_public_files(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    _allow(
        f"public_files:{ip}",
        window=settings.PUBLIC_FILES_RL_WINDOW_SEC,
        max_req=settings.PUBLIC_FILES_RL_MAX_REQ,
    )


def rate_limit_auth_login(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    _allow(
        f"auth_login:{ip}",
        window=settings.AUTH_LOGIN_RL_WINDOW_SEC,
        max_req=settings.AUTH_LOGIN_RL_MAX_REQ,
    )


def rate_limit_auth_refresh(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    _allow(
        f"auth_refresh:{ip}",
        window=settings.AUTH_REFRESH_RL_WINDOW_SEC,
        max_req=settings.AUTH_REFRESH_RL_MAX_REQ,
    )


def _reset_rate_limits_for_tests() -> None:
    _BUCKETS.clear()
