from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.shared.domain.errors import (
    Conflict,
    DomainError,
    Forbidden,
    NotFound,
    ValidationError,
)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError):
        status = 400
        if isinstance(exc, NotFound):
            status = 404
        elif isinstance(exc, Forbidden):
            status = 403
        elif isinstance(exc, Conflict):
            status = 409
        elif isinstance(exc, ValidationError):
            status = 422

        return JSONResponse(
            status_code=status,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                }
            },
        )
