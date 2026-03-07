from __future__ import annotations

import time
import uuid

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request

from app.api.v1.errors import install_error_handlers
from app.api.v1.routers import router as v1_router
from app.core.config import settings
from app.shared.infrastructure.observability import (
    configure_logging,
    get_logger,
    log_event,
    reset_request_id,
    set_request_id,
)


configure_logging()
logger = get_logger(__name__)


def _cors_origins() -> list[str]:
    origins: list[str] = []
    for item in settings.CORS_ALLOW_ORIGINS.split(","):
        value = item.strip().rstrip("/")
        if value and value not in origins:
            origins.append(value)
    return origins


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
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        token = set_request_id(request_id)
        started_at = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
            log_event(
                logger,
                "http.request.failed",
                level="exception",
                method=request.method,
                path=request.url.path,
                query=str(request.url.query or ""),
                client_ip=(request.client.host if request.client else None),
                duration_ms=elapsed_ms,
                error=str(exc),
            )
            raise

        response.headers["X-Request-ID"] = request_id
        elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
        try:
            log_event(
                logger,
                "http.request.completed",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                query=str(request.url.query or ""),
                client_ip=(request.client.host if request.client else None),
                duration_ms=elapsed_ms,
            )
            return response
        finally:
            reset_request_id(token)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    app.include_router(v1_router)
    return app


app = create_app()
