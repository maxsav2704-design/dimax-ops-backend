from __future__ import annotations

import json
import logging
from contextvars import ContextVar, Token
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID


_request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)


def configure_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(level=level, format="%(message)s")
    root.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def set_request_id(request_id: str) -> Token[str | None]:
    return _request_id_ctx.set(request_id)


def reset_request_id(token: Token[str | None]) -> None:
    _request_id_ctx.reset(token)


def current_request_id() -> str | None:
    return _request_id_ctx.get()


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (UUID, Decimal)):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        raw = getattr(value, "value", value)
        return str(raw)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Exception):
        return str(value)
    return str(value)


def log_event(
    logger: logging.Logger,
    event: str,
    *,
    level: str = "info",
    **fields: Any,
) -> None:
    payload = {"event": event}
    request_id = current_request_id()
    if request_id:
        payload["request_id"] = request_id
    for key, value in fields.items():
        payload[key] = _json_safe(value)

    message = json.dumps(payload, ensure_ascii=True, sort_keys=True)
    log_method = getattr(logger, level, None)
    if not callable(log_method):
        log_method = logger.info
    log_method(message)
