"""Business Opportunity Score as a service: scope resolution, data loading, persistence.

The scoring maths lives in ml/scoring/engine.py; this module only wires it to the warehouse.
"""

from __future__ import annotations

import uuid
from typing import Literal

import pandas as pd
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import metrics
from app.db.models import District, Recommendation, Region
from app.services import features as feat
from app.services.statistics import NotFoundError
from ml.scoring import engine
from ml.scoring.profiles import load_profiles, load_targets

Target = Literal["high_growth", "stable_demand", "low_competition"]


class BusinessType(BaseModel):
    business_type: str
    display_name: dict[str, str]
    min_budget_uzs: int
    default_level: str
    factors: list[dict]


class RecommendRequest(BaseModel):
    business_type: str
    region: str | None = None  # region SOATO → rank its districts
    level: Literal["region", "district"] | None = None
    budget_uzs: int | None = None
    target: Target | None = None
    weights_override: dict[str, float] | None = None
    limit: int = 20

    model_config = {
        "json_schema_extra": {"examples": [{"business_type": "pharmacy", "region": "1730", "budget_uzs": 700000000}]}
    }


def list_business_types() -> list[BusinessType]:
    return [
        BusinessType(
            business_type=p.business_type,
            display_name=p.display_name.model_dump(),
            min_budget_uzs=p.min_budget_uzs,
            default_level=p.default_level,
            factors=[f.model_dump() for f in p.active_factors()],
        )
        for p in load_profiles().values()
    ]


def _entities(db: Session, level: str, region: str | None) -> pd.DataFrame:
    if level == "region":
        rows = db.execute(select(Region.soato_code, Region.name_en, Region.geom_approx)).all()
        return pd.DataFrame(
            [
                {"soato": s, "name": n, "level": "region", "region_soato": s, "kind": "region", "geom_approx": g}
                for s, n, g in rows
            ]
        )
    q = select(District.soato_code, District.name_en, District.kind, District.geom_approx, Region.soato_code).join(
        Region, Region.id == District.region_id
    )
    if region:
        q = q.where(Region.soato_code == region)
    rows = db.execute(q).all()
    return pd.DataFrame(
        [
            {"soato": s, "name": n, "level": "district", "region_soato": r, "kind": k, "geom_approx": g}
            for s, n, k, g, r in rows
        ]
    )


def recommend(db: Session, req: RecommendRequest, persist: bool = True, request_id: str | None = None) -> dict:
    profiles = load_profiles()
    profile = profiles.get(req.business_type)
    if profile is None:
        raise NotFoundError(f"Unknown business type '{req.business_type}'. Available: {sorted(profiles)}")
    if req.region and db.scalar(select(Region.id).where(Region.soato_code == req.region)) is None:
        raise NotFoundError(f"Unknown region '{req.region}'")
    level = "district" if req.region else (req.level or profile.default_level)

    ents = _entities(db, level, req.region)
    names = [f.feature for f in profile.active_factors()]
    data = engine.ScoringInput(
        entities=ents,
        features=feat.get_features(db, level, names, list(ents["soato"])),
        sources=feat.feature_sources(db),
    )
    if data.features.empty:
        raise NotFoundError("No features computed yet — run `python manage.py features --local`.")
    try:
        out = engine.score(
            data,
            profile,
            weights_override=req.weights_override,
            target=req.target,
            targets=load_targets(),
            budget_uzs=req.budget_uzs,
        )
    except ValueError as e:
        raise NotFoundError(str(e)) from e

    rid = request_id or uuid.uuid4().hex
    total_ranked = len(out["results"])
    out["results"] = out["results"][: max(1, min(req.limit, 250))]
    result = {
        "request_id": rid,
        "scope": {"level": level, "region_soato": req.region, "candidates": len(ents), "ranked": total_ranked},
        **out,
    }
    metrics.RECO_REQUESTS.labels(req.business_type).inc()
    for r in out["results"]:
        metrics.RECO_SCORE.labels(req.business_type).observe(r["score"])
    if out["excluded_insufficient_data"]:
        metrics.RECO_LOW_COVERAGE.labels(req.business_type).inc(len(out["excluded_insufficient_data"]))
    if persist:
        db.add(
            Recommendation(
                request_id=rid,
                business_type=req.business_type,
                scope_level=level,
                region_soato=req.region,
                target=req.target,
                data_mode=out["data_mode"],
                top=[r["entity"]["soato"] for r in out["results"][:10]],
                result={k: v for k, v in result.items() if k != "results"} | {"results": out["results"][:10]},
            )
        )
        db.commit()
    return result
