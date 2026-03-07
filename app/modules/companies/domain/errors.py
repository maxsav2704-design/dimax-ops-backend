from __future__ import annotations

from app.shared.domain.errors import Conflict, NotFound


class CompanyAlreadyExists(Conflict):
    pass


class CompanyNotFound(NotFound):
    pass


class CompanyPlanLimitExceeded(Conflict):
    pass
