from __future__ import annotations

from app.shared.domain.errors import Conflict


class DoorTypeCodeAlreadyExists(Conflict):
    pass

