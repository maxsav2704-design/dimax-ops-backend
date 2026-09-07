from __future__ import annotations

import re
import time
import uuid

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.api.v1.errors import install_error_handlers
from app.api.v1.routers import router as v1_router
from app.core.config import settings
from app.shared.infrastructure.db.session import engine
from app.shared.infrastructure.observability import (
    configure_logging,
    get_logger,
    log_event,
    reset_request_id,
    set_request_id,
)


configure_logging()
logger = get_logger(__name__)

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def _cors_origins() -> list[str]:
    origins: list[str] = []
    for item in settings.CORS_ALLOW_ORIGINS.split(","):
        value = item.strip().rstrip("/")
        if value and value not in origins:
            origins.append(value)
    return origins


def _request_id(request: Request) -> str:
    candidate = (request.headers.get("X-Request-ID") or "").strip()
    if candidate and _REQUEST_ID_PATTERN.fullmatch(candidate):
        return candidate
    return uuid.uuid4().hex


def _request_path_for_log(request: Request) -> str:
    route = request.scope.get("route")
    route_path = getattr(route, "path", None)
    if isinstance(route_path, str) and route_path:
        api_prefix = v1_router.prefix.rstrip("/")
        is_api_request = request.url.path == api_prefix or request.url.path.startswith(
            f"{api_prefix}/"
        )
        route_has_prefix = route_path == api_prefix or route_path.startswith(
            f"{api_prefix}/"
        )
        if api_prefix and is_api_request and not route_has_prefix:
            return f"{api_prefix}/{route_path.lstrip('/')}"
        return route_path
    return "<unmatched>"


def _request_query_keys(request: Request) -> list[str]:
    keys = {str(key)[:64] for key in request.query_params.keys()}
    return sorted(keys)[:25]


def create_app() -> FastAPI:
    app = FastAPI(title="DIMAX Operations Suite")
    install_error_handlers(app)
    origins = _cors_origins()
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.middleware("http")
    async def request_observability(request: Request, call_next):
        request_id = _request_id(request)
        token = set_request_id(request_id)
        started_at = time.perf_counter()
        try:
            try:
                response = await call_next(request)
            except Exception as exc:
                elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
                log_event(
                    logger,
                    "http.request.failed",
                    level="error",
                    method=request.method,
                    path=_request_path_for_log(request),
                    query_keys=_request_query_keys(request),
                    client_ip=(request.client.host if request.client else None),
                    duration_ms=elapsed_ms,
                    error_type=type(exc).__name__,
                )
                response = JSONResponse(
                    status_code=500,
                    content={
                        "error": {
                            "code": "INTERNAL_ERROR",
                            "message": "Internal server error",
                            "field": None,
                            "meta": None,
                        }
                    },
                )
                response.headers["X-Request-ID"] = request_id
                return response

            response.headers["X-Request-ID"] = request_id
            elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
            log_event(
                logger,
                "http.request.completed",
                method=request.method,
                path=_request_path_for_log(request),
                status_code=response.status_code,
                query_keys=_request_query_keys(request),
                client_ip=(request.client.host if request.client else None),
                duration_ms=elapsed_ms,
            )
            return response
        finally:
            reset_request_id(token)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/ready", include_in_schema=False)
    def readiness():
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except Exception as exc:
            log_event(
                logger,
                "app.readiness.failed",
                level="warning",
                check="database",
                error_type=type(exc).__name__,
            )
            return JSONResponse(
                status_code=503,
                content={
                    "status": "not_ready",
                    "checks": {"database": "unavailable"},
                },
            )
        return {"status": "ok", "checks": {"database": "ready"}}

    app.include_router(v1_router)
    return app


app = create_app()
