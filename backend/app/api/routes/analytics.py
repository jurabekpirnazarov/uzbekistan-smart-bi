"""Analytics routes (PLAN.md Phase 6) — thin wrappers over app.services."""

from __future__ import annotations

from typing import Annotated, Literal

from cachetools import TTLCache
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.services import feedback, forecasts, geo, monitoring, recommendations
from app.services import statistics as stats

router = APIRouter(tags=["analytics"])
DB = Annotated[Session, Depends(get_session)]
_geo_cache: TTLCache = TTLCache(maxsize=256, ttl=600)


@router.get("/compare", response_model=stats.Comparison)
def compare(
    db: DB,
    indicator: str,
    entities: Annotated[str, Query(description="comma-separated region/district SOATO codes", max_length=400)],
    year: Annotated[int | None, Query(ge=1990, le=2100)] = None,
) -> stats.Comparison:
    return stats.compare(db, indicator, [e.strip() for e in entities.split(",") if e.strip()][:20], year)


@router.get("/territories/search", response_model=list[stats.TerritoryMatch])
def territory_search(
    db: DB, q: Annotated[str, Query(min_length=2, max_length=80)], level: Literal["region", "district"] | None = None
) -> list[stats.TerritoryMatch]:
    return stats.find_territory(db, q, level)


@router.get("/geo/regions")
def geo_regions(
    db: DB, metric: str = "population_total", year: Annotated[int | None, Query(ge=1990, le=2100)] = None
) -> dict:
    key = ("region", metric, year, None)
    if key not in _geo_cache:
        _geo_cache[key] = geo.geo_layer(db, "region", metric, year)
    return _geo_cache[key]


@router.get("/geo/districts")
def geo_districts(
    db: DB,
    metric: str = "population_total",
    region: str | None = None,
    year: Annotated[int | None, Query(ge=1990, le=2100)] = None,
) -> dict:
    key = ("district", metric, year, region)
    if key not in _geo_cache:
        _geo_cache[key] = geo.geo_layer(db, "district", metric, year, region)
    return _geo_cache[key]


@router.get("/business-types", response_model=list[recommendations.BusinessType])
def business_types() -> list[recommendations.BusinessType]:
    return recommendations.list_business_types()


@router.post("/recommend")
def recommend(db: DB, req: recommendations.RecommendRequest) -> dict:
    return recommendations.recommend(db, req)


@router.get("/forecast/{indicator}/{level}/{soato}", response_model=forecasts.Forecast)
def forecast(
    db: DB,
    indicator: str,
    level: Literal["country", "region", "district"],
    soato: str,
    horizon: Annotated[int, Query(ge=1, le=3)] = 3,
) -> forecasts.Forecast:
    return forecasts.get_forecast(db, indicator, level, soato, horizon)


@router.get("/forecast-targets", response_model=list[str])
def forecast_targets(db: DB) -> list[str]:
    return forecasts.forecast_targets(db)


@router.post("/feedback")
def post_feedback(db: DB, fb: feedback.FeedbackIn) -> dict:
    return feedback.save_feedback(db, fb)


@router.get("/monitoring/data")
def monitoring_data(db: DB) -> dict:
    return monitoring.data_health(db)


@router.get("/monitoring/models")
def monitoring_models(db: DB) -> dict:
    return monitoring.model_health(db)


@router.get("/monitoring/recommendations")
def monitoring_recommendations(db: DB) -> dict:
    return monitoring.reco_health(db)


@router.get("/monitoring/agent")
def monitoring_agent(db: DB, days: Annotated[int, Query(ge=1, le=90)] = 7) -> dict:
    return monitoring.agent_health(db, days)
