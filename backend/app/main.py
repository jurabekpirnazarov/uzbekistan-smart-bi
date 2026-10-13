"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi.errors import RateLimitExceeded

from app import __version__
from app.api.routes import analytics, chat, health, statistics
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.metrics import register_db_collector
from app.core.middleware import RequestIdMiddleware
from app.core.ratelimit import limiter
from app.services.statistics import NotFoundError

API_PREFIX = "/api/v1"


def error(status: int, code: str, message: str, details: object = None) -> JSONResponse:
    """Consistent error model: {code, message, details}."""
    return JSONResponse(status_code=status, content={"code": code, "message": message, "details": details})


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(title=settings.app_name, version=__version__, docs_url="/docs", redoc_url=None)
    app.state.limiter = limiter
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
    app.include_router(analytics.router, prefix=API_PREFIX)
    app.include_router(chat.router, prefix=API_PREFIX)

    @app.exception_handler(NotFoundError)
    async def not_found(_: Request, exc: NotFoundError) -> JSONResponse:
        return error(404, "not_found", str(exc))

    @app.exception_handler(RequestValidationError)
    async def invalid(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]
        return error(422, "validation_error", "Invalid request parameters", details)

    @app.exception_handler(RateLimitExceeded)
    async def rate_limited(_: Request, exc: RateLimitExceeded) -> JSONResponse:
        return error(429, "rate_limited", f"Too many requests: {exc.detail}. Please wait a minute.")

    Instrumentator(excluded_handlers=["/metrics"]).instrument(app).expose(app, include_in_schema=False)
    register_db_collector()

    get_logger("app").info(
        "startup", environment=settings.environment, data_mode=settings.data_mode, llm_enabled=settings.llm_enabled
    )
    return app


app = create_app()
