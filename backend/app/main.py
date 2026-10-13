"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator

from app import __version__
from app.api.routes import chat, health, statistics
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestIdMiddleware
from app.services.statistics import NotFoundError

API_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(title=settings.app_name, version=__version__, docs_url="/docs", redoc_url=None)
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    # /health at the root for Docker healthchecks, and under /api/v1 for the frontend.
    app.include_router(health.router)
    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(statistics.router, prefix=API_PREFIX)
    app.include_router(chat.router, prefix=API_PREFIX)

    @app.exception_handler(NotFoundError)
    async def not_found(_: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"code": "not_found", "message": str(exc), "details": None})

    Instrumentator(excluded_handlers=["/metrics"]).instrument(app).expose(app, include_in_schema=False)

    get_logger("app").info(
        "startup", environment=settings.environment, data_mode=settings.data_mode, llm_enabled=settings.llm_enabled
    )
    return app


app = create_app()
