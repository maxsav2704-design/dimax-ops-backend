from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.errors import install_error_handlers
from app.api.v1.routers import router as v1_router
from app.core.config import settings


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

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    app.include_router(v1_router)
    return app


app = create_app()
