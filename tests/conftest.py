"""Shared test helpers. Integration tests run against the local warehouse and skip when it is not loaded."""

from __future__ import annotations

from functools import lru_cache

import pytest
from sqlalchemy import text


@lru_cache
def db_loaded() -> bool:
    try:
        from app.db.session import get_engine

        with get_engine().connect() as c:
            return (c.execute(text("SELECT count(*) FROM features")).scalar() or 0) > 0
    except Exception:
        return False


requires_db = pytest.mark.skipif(not db_loaded(), reason="warehouse not running / features not computed")


@pytest.fixture
def no_openai_key(monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    """Force the rule-based agent (CLAUDE.md rule 10)."""
    from app.core.config import get_settings

    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
