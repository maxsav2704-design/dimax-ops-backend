from __future__ import annotations

from app.shared.domain.errors import ValidationError


class InvalidPhone(ValidationError):
    code = "INVALID_PHONE"


class InvalidWazeUrl(ValidationError):
    code = "INVALID_WAZE_URL"
