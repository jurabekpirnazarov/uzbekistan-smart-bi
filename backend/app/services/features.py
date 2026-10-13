"""Read access to the `features` table (computed by ml/features/pipeline.py)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd
import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import District, Feature, Indicator, Observation, Region

DEFINITIONS = Path(__file__).resolve().parents[3] / "ml" / "features" / "definitions.yaml"


@lru_cache
def feature_definitions() -> dict[str, dict]:
    return yaml.safe_load(DEFINITIONS.read_text(encoding="utf-8"))


def _input_codes(spec: dict) -> list[str]:
    codes = [spec[k] for k in ("indicator", "num", "den") if k in spec]
    if spec.get("type") == "per_capita" and "den" not in spec:
        codes.append("population_total")
    return codes


def feature_sources(db: Session) -> dict[str, list[dict]]:
    """feature -> official datasets it is computed from (traceability, CLAUDE.md rule 3)."""
    rows = db.execute(
        select(Indicator.code, Indicator.siat_dataset_id, func.max(Observation.source_url))
        .outerjoin(Observation, Observation.indicator_id == Indicator.id)
        .group_by(Indicator.code, Indicator.siat_dataset_id)
    ).all()
    by_code = {c: {"indicator": c, "dataset_id": d, "url": u} for c, d, u in rows}
    out: dict[str, list[dict]] = {}
    for name, spec in feature_definitions().items():
        out[name] = [by_code[c] for c in _input_codes(spec) if c in by_code]
    out["forecast_population_growth"] = [by_code[c] for c in ["population_total"] if c in by_code]
    out["forecast_business_growth"] = [by_code[c] for c in ["enterprises_active"] if c in by_code]
    return out


def get_features(
    db: Session,
    level: str,
    names: list[str],
    soatos: list[str] | None = None,
    year: int | None = None,
) -> pd.DataFrame:
    """Long frame: soato, feature, year, value, is_synthetic, quality_flag (all years unless `year`)."""
    if level == "district":
        ent = select(District.soato_code.label("soato"), District.id.label("eid")).subquery()
        join_on = Feature.district_id == ent.c.eid
    elif level == "region":
        ent = select(Region.soato_code.label("soato"), Region.id.label("eid")).subquery()
        join_on = (Feature.region_id == ent.c.eid) & Feature.district_id.is_(None)
    else:
        ent = select(func.cast("1700", Region.soato_code.type).label("soato")).subquery()
        join_on = Feature.region_id.is_(None)
    q = (
        select(
            ent.c.soato,
            Feature.name.label("feature"),
            Feature.year,
            Feature.value,
            Feature.is_synthetic,
            Feature.quality_flag,
        )
        .join(ent, join_on)
        .where(Feature.level == level, Feature.name.in_(names))
    )
    if soatos is not None:
        q = q.where(ent.c.soato.in_(soatos))
    if year is not None:
        q = q.where(Feature.year == year)
    rows = db.execute(q).all()
    return pd.DataFrame(rows, columns=["soato", "feature", "year", "value", "is_synthetic", "quality_flag"])


def features_available(db: Session) -> bool:
    return db.scalar(select(func.count(Feature.id)).limit(1)) not in (None, 0)
