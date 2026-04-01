from __future__ import annotations

from app.shared.domain.errors import Forbidden, ValidationError


class DoorNotAssigned(Forbidden):
    code = "DOOR_NOT_ASSIGNED"


class InvalidTransition(ValidationError):
    code = "INVALID_TRANSITION"
