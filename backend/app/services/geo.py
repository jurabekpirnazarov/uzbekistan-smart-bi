"""GeoJSON for the map: region/district geometry (PostGIS) joined with an indicator value."""

from __future__ import annotations

import json

from cachetools import TTLCache
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services import statistics as stats

_geometry_cache: TTLCache = TTLCache(maxsize=4, ttl=3600)


def _geometries(db: Session, level: str) -> list[dict]:
    """Static geometry (cached for an hour): polygons, or centroid points for approximate districts."""
    if level in _geometry_cache:
        return _geometry_cache[level]
    if level == "region":
        sql = """SELECT soato_code, name_en, name_uz, name_ru, NULL AS kind, soato_code AS region_soato,
                        geom_approx, centroid_lat, centroid_lon, ST_AsGeoJSON(geom, 4) AS g
                 FROM regions"""
    else:
        sql = """SELECT d.soato_code, d.name_en, d.name_uz, d.name_ru, d.kind, r.soato_code AS region_soato,
                        d.geom_approx, d.centroid_lat, d.centroid_lon, ST_AsGeoJSON(d.geom, 4) AS g
                 FROM districts d JOIN regions r ON r.id = d.region_id"""
    feats = []
    for row in db.execute(text(sql)).mappings():
        geom = (
            json.loads(row["g"])
            if row["g"]
            else (
                {"type": "Point", "coordinates": [row["centroid_lon"], row["centroid_lat"]]}
                if row["centroid_lat"] is not None
                else None
            )
        )
        if geom is None:
            continue
        feats.append(
            {
                "type": "Feature",
                "geometry": geom,
                "properties": {
                    "soato": row["soato_code"],
                    "name_en": row["name_en"],
                    "name_uz": row["name_uz"],
                    "name_ru": row["name_ru"],
                    "kind": row["kind"],
                    "region_soato": row["region_soato"],
                    "geom_approx": bool(row["geom_approx"]),
                    "centroid": [row["centroid_lon"], row["centroid_lat"]],
                },
            }
        )
    _geometry_cache[level] = feats
    return feats


def geo_layer(
    db: Session, level: str, metric: str = "population_total", year: int | None = None, region: str | None = None
) -> dict:
    """FeatureCollection with `value`, `rank` and `share` properties for the chosen indicator."""
    ranking = stats.get_ranking(db, metric, level, year, region)  # type: ignore[arg-type]
    by = {i.soato: i for i in ranking.items}
    out = []
    for f in _geometries(db, level):
        p = f["properties"]
        if region and p["region_soato"] != region:
            continue
        item = by.get(p["soato"])
        out.append(
            {
                **f,
                "properties": {
                    **p,
                    "value": item.value if item else None,
                    "rank": item.rank if item else None,
                    "share": item.share if item else None,
                },
            }
        )
    values = [i.value for i in ranking.items]
    return {
        "type": "FeatureCollection",
        "features": out,
        "metric": metric,
        "level": level,
        "year": ranking.year,
        "years_available": ranking.years_available,
        "min": min(values) if values else None,
        "max": max(values) if values else None,
        "meta": ranking.meta.model_dump(mode="json"),
    }
