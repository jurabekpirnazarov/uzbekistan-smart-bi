"""Health checks. Routers and the MCP server call this; no logic lives in the API layer."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel
from sqlalchemy import text

from app.db.session import get_engine


class HealthStatus(BaseModel):
    status: Literal["ok", "degraded"]
    db: Literal["ok", "down"]
    version: str


def check_database() -> bool:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def get_health(version: str) -> HealthStatus:
    db_ok = check_database()
    return HealthStatus(status="ok" if db_ok else "degraded", db="ok" if db_ok else "down", version=version)
