from __future__ import annotations

import time
from collections import deque
from typing import Deque, Dict

from fastapi import Request

from app.core.config import settings
from app.shared.domain.errors import Forbidden

_BUCKETS: Dict[str, Deque[float]] = {}


def rate_limit_public_files(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    window = settings.PUBLIC_FILES_RL_WINDOW_SEC
    max_req = settings.PUBLIC_FILES_RL_MAX_REQ

    dq = _BUCKETS.get(ip)
    if dq is None:
        dq = deque()
        _BUCKETS[ip] = dq

    while dq and dq[0] <= now - window:
        dq.popleft()

    if len(dq) >= max_req:
        raise Forbidden("Too many requests. Slow down.")

    dq.append(now)
