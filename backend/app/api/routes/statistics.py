"""Statistics routes — thin wrappers over app.services.statistics."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.services import statistics as svc

router = APIRouter(tags=["statistics"])
DB = Annotated[Session, Depends(get_session)]


@router.get("/overview", response_model=svc.Overview)
def overview(db: DB) -> svc.Overview:
    return svc.get_overview(db)


@router.get("/indicators", response_model=list[svc.IndicatorOut])
def indicators(db: DB, category: str | None = None) -> list[svc.IndicatorOut]:
    return svc.list_indicators(db, category)


@router.get("/regions", response_model=list[svc.RegionOut])
def regions(db: DB) -> list[svc.RegionOut]:
    return svc.list_regions(db)


@router.get("/regions/{soato}/districts", response_model=list[svc.DistrictOut])
def districts(db: DB, soato: str) -> list[svc.DistrictOut]:
    return svc.list_districts(db, soato)


@router.get("/statistics", response_model=svc.Ranking)
def statistics(
    db: DB,
    indicator: str,
    level: Literal["region", "district"] = "region",
    year: Annotated[int | None, Query(ge=1990, le=2100)] = None,
    region: str | None = None,
) -> svc.Ranking:
    return svc.get_ranking(db, indicator, level, year, region)


@router.get("/timeseries/{indicator}/{level}/{soato}", response_model=svc.TimeSeries)
def timeseries(db: DB, indicator: str, level: Literal["country", "region", "district"], soato: str) -> svc.TimeSeries:
    return svc.get_timeseries(db, indicator, level, soato)
