from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.shared.domain.errors import (
    Conflict,
    DomainError,
    Forbidden,
    NotFound,
    ValidationError,
)


def _error_content(*, code: str, message: str, details=None) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details,
        }
    }


def _http_status_to_error_code(status_code: int) -> str | None:
    if status_code == 400:
        return "BAD_REQUEST"
    if status_code == 401:
        return "UNAUTHORIZED"
    if status_code == 403:
        return "FORBIDDEN"
    if status_code == 404:
        return "NOT_FOUND"
    if status_code == 409:
        return "CONFLICT"
    if status_code == 422:
        return "VALIDATION_ERROR"
    return None


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
            content=_error_content(
                code=exc.code,
                message=exc.message,
                details=exc.details,
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_error_handler(
        request: Request,
        exc: RequestValidationError,
    ):
        return JSONResponse(
            status_code=422,
            content=_error_content(
                code="VALIDATION_ERROR",
                message="Request validation failed",
                details=jsonable_encoder(exc.errors()),
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request,
        exc: StarletteHTTPException,
    ):
        error_code = _http_status_to_error_code(exc.status_code)
        if error_code is not None:
            return JSONResponse(
                status_code=exc.status_code,
                content=_error_content(
                    code=error_code,
                    message=str(exc.detail),
                    details=None,
                ),
                headers=exc.headers,
            )

        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=exc.headers,
        )
