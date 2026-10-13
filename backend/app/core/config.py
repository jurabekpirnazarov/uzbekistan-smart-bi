"""Application settings, read from environment variables / .env (never hard-coded secrets)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Uzbekistan Smart Business Intelligence"
    environment: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/sbi"
    vector_db_url: str | None = None

    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1-mini"
    openai_embed_model: str = "text-embedding-3-small"
    mapbox_token: str | None = None

    data_mode: Literal["official", "demo"] = "official"
    mlflow_tracking_uri: str = "http://localhost:5000"
    otel_enabled: bool = False

    # scheduled data refresh (pipelines/refresh.py)
    refresh_every_days: int = 3
    refresh_at: str = "03:00"  # local time HH:MM

    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:5174", "http://localhost:8080"]

    @property
    def llm_enabled(self) -> bool:
        return bool(self.openai_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
