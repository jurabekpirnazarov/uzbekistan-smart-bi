"""Warehouse, analytics and agent tables.

PostGIS `geom` columns on regions/districts and the RAG `tsv` column are managed by raw SQL in the
migrations (they are not mapped here; alembic env.py ignores them during autogenerate)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DataSource(Base):
    __tablename__ = "data_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    url: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(16))  # siat | synthetic | manual | geo
    license: Mapped[str | None] = mapped_column(Text)
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Region(Base):
    __tablename__ = "regions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    soato_code: Mapped[str] = mapped_column(String(16), unique=True)
    name_en: Mapped[str] = mapped_column(Text)
    name_uz: Mapped[str | None] = mapped_column(Text)
    name_ru: Mapped[str | None] = mapped_column(Text)
    centroid_lat: Mapped[float | None] = mapped_column(Double)
    centroid_lon: Mapped[float | None] = mapped_column(Double)
    geom_approx: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class District(Base):
    __tablename__ = "districts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    soato_code: Mapped[str] = mapped_column(String(16), unique=True)
    region_id: Mapped[int] = mapped_column(ForeignKey("regions.id"), index=True)
    name_en: Mapped[str] = mapped_column(Text)
    name_uz: Mapped[str | None] = mapped_column(Text)
    name_ru: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(16))  # district | city
    centroid_lat: Mapped[float | None] = mapped_column(Double)
    centroid_lon: Mapped[float | None] = mapped_column(Double)
    geom_approx: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class Indicator(Base):
    __tablename__ = "indicators"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name_en: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(32))
    unit: Mapped[str] = mapped_column(String(64))
    source_unit: Mapped[str | None] = mapped_column(String(64))
    unit_multiplier: Mapped[float] = mapped_column(Double, default=1.0)
    frequency: Mapped[str] = mapped_column(String(16), default="annual")
    additive: Mapped[bool] = mapped_column(Boolean)
    higher_is_better: Mapped[bool] = mapped_column(Boolean, default=True)
    siat_dataset_id: Mapped[int | None] = mapped_column(Integer)
    source_name: Mapped[str | None] = mapped_column(Text)  # dataset name as published by SIAT


class Observation(Base):
    __tablename__ = "observations"
    __table_args__ = (
        UniqueConstraint(
            "indicator_id",
            "level",
            "region_id",
            "district_id",
            "year",
            "quarter",
            "month",
            "source_id",
            name="uq_observation",
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_observations_indicator_level_year", "indicator_id", "level", "year"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    indicator_id: Mapped[int] = mapped_column(ForeignKey("indicators.id"))
    level: Mapped[str] = mapped_column(String(16))  # country | region | district
    region_id: Mapped[int | None] = mapped_column(ForeignKey("regions.id"), index=True)
    district_id: Mapped[int | None] = mapped_column(ForeignKey("districts.id"), index=True)
    year: Mapped[int] = mapped_column(SmallInteger)
    quarter: Mapped[int | None] = mapped_column(SmallInteger)
    month: Mapped[int | None] = mapped_column(SmallInteger)
    period_label: Mapped[str] = mapped_column(String(32))
    value: Mapped[float] = mapped_column(Double)
    unit: Mapped[str] = mapped_column(String(64))
    source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"))
    source_url: Mapped[str | None] = mapped_column(Text)
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_sha256: Mapped[str | None] = mapped_column(String(64))
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("data_sources.id"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16))
    datasets_ok: Mapped[int] = mapped_column(Integer, default=0)
    rows_in: Mapped[int] = mapped_column(Integer, default=0)
    rows_loaded: Mapped[int] = mapped_column(Integer, default=0)
    rows_rejected: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)


# --- Phase 3: features ----------------------------------------------------------------------


class Feature(Base):
    __tablename__ = "features"
    __table_args__ = (
        UniqueConstraint(
            "name", "level", "region_id", "district_id", "year", name="uq_feature", postgresql_nulls_not_distinct=True
        ),
        Index("ix_features_name_level_year", "name", "level", "year"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    level: Mapped[str] = mapped_column(String(16))
    region_id: Mapped[int | None] = mapped_column(ForeignKey("regions.id"))
    district_id: Mapped[int | None] = mapped_column(ForeignKey("districts.id"))
    year: Mapped[int] = mapped_column(SmallInteger)
    value: Mapped[float | None] = mapped_column(Double)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    quality_flag: Mapped[str | None] = mapped_column(String(64))
    lineage: Mapped[dict | None] = mapped_column(JSON)
    feature_version: Mapped[str] = mapped_column(String(16))
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# --- Phase 4: recommendations ---------------------------------------------------------------


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[str] = mapped_column(String(64), index=True)
    business_type: Mapped[str] = mapped_column(String(64), index=True)
    scope_level: Mapped[str] = mapped_column(String(16))
    region_soato: Mapped[str | None] = mapped_column(String(16))
    target: Mapped[str | None] = mapped_column(String(32))
    data_mode: Mapped[str] = mapped_column(String(16))
    top: Mapped[list | None] = mapped_column(JSON)  # top-10 soato codes, for stability monitoring
    result: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# --- Phase 5: forecasts and model metrics --------------------------------------------------


class Prediction(Base):
    __tablename__ = "predictions"
    __table_args__ = (Index("ix_predictions_lookup", "indicator_code", "level", "soato"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(32))
    indicator_code: Mapped[str] = mapped_column(String(64))
    level: Mapped[str] = mapped_column(String(16))
    soato: Mapped[str] = mapped_column(String(16))
    model: Mapped[str] = mapped_column(String(32))
    origin_year: Mapped[int] = mapped_column(SmallInteger)
    year: Mapped[int] = mapped_column(SmallInteger)
    horizon: Mapped[int] = mapped_column(SmallInteger)
    yhat: Mapped[float] = mapped_column(Double)
    lo80: Mapped[float | None] = mapped_column(Double)
    hi80: Mapped[float | None] = mapped_column(Double)
    lo95: Mapped[float | None] = mapped_column(Double)
    hi95: Mapped[float | None] = mapped_column(Double)
    history_points: Mapped[int] = mapped_column(SmallInteger)
    low_confidence: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ModelMetric(Base):
    __tablename__ = "model_metrics"
    __table_args__ = (Index("ix_model_metrics_kind", "kind", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(16))  # forecast | reco | agent | rag
    split: Mapped[str] = mapped_column(String(16), default="backtest")  # backtest | live | eval
    indicator_code: Mapped[str | None] = mapped_column(String(64))
    level: Mapped[str | None] = mapped_column(String(16))
    model: Mapped[str | None] = mapped_column(String(64))
    horizon: Mapped[int | None] = mapped_column(SmallInteger)
    metric: Mapped[str] = mapped_column(String(32))
    value: Mapped[float | None] = mapped_column(Double)
    is_selected: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# --- Phase 8: agent runs, feedback, RAG -----------------------------------------------------


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    question: Mapped[str] = mapped_column(Text)
    lang: Mapped[str] = mapped_column(String(4))
    intent: Mapped[str | None] = mapped_column(String(32))
    mode: Mapped[str] = mapped_column(String(16))  # llm | fallback
    model: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))  # ok | error | insufficient
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Double, default=0.0)
    tool_count: Mapped[int] = mapped_column(Integer, default=0)
    verification_failures: Mapped[int] = mapped_column(Integer, default=0)
    answer: Mapped[str | None] = mapped_column(Text)


class AgentToolCall(Base):
    __tablename__ = "agent_tool_calls"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    args: Mapped[dict | None] = mapped_column(JSON)
    ok: Mapped[bool] = mapped_column(Boolean)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[str | None] = mapped_column(String(64), index=True)
    target: Mapped[str] = mapped_column(String(16), default="chat")  # chat | recommendation
    rating: Mapped[int] = mapped_column(SmallInteger)  # +1 / -1
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RagChunk(Base):
    __tablename__ = "rag_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    doc_id: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list | None] = mapped_column(JSON)  # OpenAI embedding when a key is set; else BM25 only


# --- Phase 10: batch-job metrics exported as gauges -----------------------------------------


class MonitorMetric(Base):
    __tablename__ = "monitor_metrics"
    __table_args__ = (Index("ix_monitor_metrics_name", "name", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    labels: Mapped[dict] = mapped_column(JSON, default=dict)
    value: Mapped[float | None] = mapped_column(Double)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
