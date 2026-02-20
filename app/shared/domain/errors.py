class DomainError(Exception):
    code = "DOMAIN_ERROR"

    def __init__(self, message: str, *, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFound(DomainError):
    code = "NOT_FOUND"


class Forbidden(DomainError):
    code = "FORBIDDEN"


class Conflict(DomainError):
    code = "CONFLICT"


class ValidationError(DomainError):
    code = "VALIDATION_ERROR"
