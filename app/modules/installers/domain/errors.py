from __future__ import annotations

from app.shared.domain.errors import DomainError


class InvalidUserLink(DomainError):
    """User validation for link (not found, wrong company, or not INSTALLER role)."""


class UserAlreadyLinked(DomainError):
    """User is already linked to another installer."""


class InstallerRateNotFound(DomainError):
    pass


class InstallerRateAlreadyExists(DomainError):
    pass


class InstallerNotFound(DomainError):
    pass


class DoorTypeNotFound(DomainError):
    pass
