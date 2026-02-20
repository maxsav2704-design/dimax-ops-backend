from __future__ import annotations

from fastapi import FastAPI

from app.api.v1.errors import install_error_handlers
from app.api.v1.routers import router as v1_router


def create_app() -> FastAPI:
    app = FastAPI(title="DIMAX Operations Suite")
    install_error_handlers(app)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    app.include_router(v1_router)
    return app


app = create_app()
