from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ApiErrorDTO(BaseModel):
    code: str
    message: str
    details: Any | None = None


class ApiErrorResponseDTO(BaseModel):
    error: ApiErrorDTO
