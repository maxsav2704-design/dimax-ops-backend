class DomainError(Exception):
    code = "DOMAIN_ERROR"

    def __init__(
        self,
        message: str,
        *,
        details: dict | None = None,
        field: str | None = None,
        meta: dict | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.details = details or meta or {}

        derived_field = field
        if derived_field is None and isinstance(self.details, dict):
            raw_field = self.details.get("field")
            if isinstance(raw_field, str) and raw_field.strip():
                derived_field = raw_field.strip()

        derived_meta = meta
        if derived_meta is None and isinstance(self.details, dict):
            derived_meta = dict(self.details)

        if isinstance(derived_meta, dict) and derived_field:
            derived_meta.pop("field", None)

        self.field = derived_field
        self.meta = derived_meta or None


class NotFound(DomainError):
    code = "NOT_FOUND"


class Forbidden(DomainError):
    code = "FORBIDDEN"


class ForbiddenScope(Forbidden):
    code = "FORBIDDEN_SCOPE"


class Unauthorized(DomainError):
    code = "UNAUTHORIZED"


class InvalidCredentials(Unauthorized):
    code = "INVALID_CREDENTIALS"


class RefreshTokenReuse(Unauthorized):
    code = "REFRESH_TOKEN_REUSE"


class Conflict(DomainError):
    code = "CONFLICT"


class ValidationError(DomainError):
    code = "VALIDATION_ERROR"
