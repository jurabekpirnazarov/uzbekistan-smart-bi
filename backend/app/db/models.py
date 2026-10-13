"""Warehouse tables (lean subset of the PLAN.md Phase 1 schema; geometry arrives in Phase 2)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
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


class District(Base):
    __tablename__ = "districts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    soato_code: Mapped[str] = mapped_column(String(16), unique=True)
    region_id: Mapped[int] = mapped_column(ForeignKey("regions.id"), index=True)
    name_en: Mapped[str] = mapped_column(Text)
    name_uz: Mapped[str | None] = mapped_column(Text)
    name_ru: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(16))  # district | city


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
