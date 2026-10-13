"""Batch monitoring job (PLAN.md Phase 10): data quality, feature drift, realised forecast error,
recommendation stability. Results go to `monitor_metrics`; the backend exports them on /metrics.

Usage:  python -m monitoring.drift            (or: python manage.py monitor --local)
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import func, insert, select, text
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.db.models import (  # noqa: E402
    DataSource,
    District,
    Feature,
    IngestionRun,
    ModelMetric,
    MonitorMetric,
    Observation,
    Recommendation,
)
from ml.forecasting.backtest import Series  # noqa: E402
from ml.forecasting.models import SINGLE_MODELS, GbmPanel  # noqa: E402
from ml.forecasting.train import load_series  # noqa: E402

PSI_BINS = 10
PSI_ALERT = 0.2
DRIFT_FEATURES = [
    "population",
    "population_growth",
    "urbanization",
    "business_density",
    "new_business_rate",
    "business_growth",
    "services_per_capita",
    "trade_per_capita",
    "food_services_per_capita",
    "clinics_per_10k",
]
REALISED_TARGETS = ["population_total", "enterprises_active", "market_services_volume"]


# --- pure helpers (unit-tested) -------------------------------------------------------------


def psi(expected: np.ndarray, actual: np.ndarray, bins: int = PSI_BINS) -> float:
    """Population Stability Index with quantile bins from `expected`. 0 = identical; > 0.2 = drift."""
    e = np.asarray(expected, dtype=float)
    a = np.asarray(actual, dtype=float)
    e, a = e[np.isfinite(e)], a[np.isfinite(a)]
    if len(e) < bins or len(a) < bins:
        return float("nan")
    edges = np.unique(np.quantile(e, np.linspace(0, 1, bins + 1)))
    if len(edges) < 3:
        return 0.0
    edges[0], edges[-1] = -np.inf, np.inf
    pe = np.histogram(e, edges)[0] / len(e)
    pa = np.histogram(a, edges)[0] / len(a)
    pe, pa = np.clip(pe, 1e-4, None), np.clip(pa, 1e-4, None)
    return float(np.sum((pa - pe) * np.log(pa / pe)))


def jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    return len(sa & sb) / len(sa | sb) if sa | sb else 1.0


# --- checks -----------------------------------------------------------------------------------


def data_quality(db: Session) -> list[tuple[str, dict, float]]:
    out: list[tuple[str, dict, float]] = []
    last = db.scalar(select(func.max(Observation.retrieved_at)))
    if last:
        out.append(("data_last_update_timestamp", {"source": "siat"}, last.timestamp()))

    for status, n in db.execute(select(IngestionRun.status, func.count()).group_by(IngestionRun.status)).all():
        out.append(("ingestion_runs_total", {"source": "siat", "status": status}, float(n)))
    run = db.scalars(select(IngestionRun).order_by(IngestionRun.started_at.desc()).limit(1)).first()
    if run:
        out.append(("ingestion_rows_total", {"source": "siat", "result": "loaded"}, float(run.rows_loaded)))
        out.append(("ingestion_rows_total", {"source": "siat", "result": "rejected"}, float(run.rows_rejected)))

    # missing ratio per indicator at district level: expected = districts × years published
    n_districts = db.scalar(select(func.count(District.id))) or 0
    rows = db.execute(
        text(
            """SELECT i.code, count(DISTINCT o.year) AS years, count(*) AS n
               FROM observations o JOIN indicators i ON i.id = o.indicator_id
               WHERE o.level = 'district' AND o.quarter IS NULL GROUP BY i.code"""
        )
    ).all()
    for code, years, n in rows:
        expected = years * n_districts
        out.append(("data_missing_ratio", {"indicator": code}, max(0.0, 1 - n / expected) if expected else 1.0))

    checks: dict[str, bool] = {}
    report = ROOT / "data" / "processed" / "quality_report.json"
    if report.exists():
        rep = json.loads(report.read_text(encoding="utf-8"))
        failed = rep.get("failed_checks", rep.get("summary", {}).get("failed_checks", 0))
        checks["siat_quality_report"] = (failed or 0) == 0
    checks["no_negative_additive_values"] = (
        db.scalar(
            text(
                """SELECT count(*) FROM observations o JOIN indicators i ON i.id = o.indicator_id
                   WHERE i.additive AND o.value < 0"""
            )
        )
        == 0
    )
    gap = db.scalar(
        text(
            """WITH p AS (SELECT o.level, o.year, sum(o.value) v FROM observations o
                          JOIN indicators i ON i.id = o.indicator_id
                          WHERE i.code = 'population_total' AND o.quarter IS NULL GROUP BY 1, 2)
               SELECT max(abs(d.v - r.v) / r.v) FROM p d JOIN p r ON r.year = d.year
               WHERE d.level = 'district' AND r.level = 'region'"""
        )
    )
    checks["district_population_sums_to_regions"] = gap is not None and gap < 0.005
    checks["all_regions_have_geometry"] = db.scalar(text("SELECT count(*) FROM regions WHERE geom IS NULL")) == 0
    checks["all_districts_located"] = db.scalar(text("SELECT count(*) FROM districts WHERE centroid_lat IS NULL")) == 0
    obs_last = db.scalar(select(func.max(Observation.year)))
    feat_last = db.scalar(select(func.max(Feature.year)).where(Feature.feature_version != "forecast"))
    checks["features_up_to_date"] = feat_last is not None and feat_last >= (obs_last or 0)
    for k, ok in checks.items():
        out.append(("data_quality_check_passed", {"check": k}, 1.0 if ok else 0.0))
    return out


def feature_drift(db: Session) -> list[tuple[str, dict, float]]:
    out = []
    for name in DRIFT_FEATURES:
        rows = db.execute(
            select(Feature.year, Feature.value).where(
                Feature.name == name, Feature.level == "district", Feature.value.is_not(None)
            )
        ).all()
        df = pd.DataFrame(rows, columns=["year", "value"])
        if df.empty:
            continue
        counts = df.groupby("year").size()
        years = sorted(counts[counts >= 0.8 * counts.max()].index)  # skip sparsely published years
        if len(years) < 2:
            continue
        v = psi(df[df.year == years[-2]]["value"].to_numpy(), df[df.year == years[-1]]["value"].to_numpy())
        if np.isfinite(v):
            out.append(("feature_drift_psi", {"feature": name, "years": f"{years[-2]}-{years[-1]}"}, v))
    return out


def realised_error(db: Session) -> list[tuple[str, dict, float]]:
    """MAPE of a forecast made one year ago (history up to last-1) against the latest official value."""
    out = []
    for ind in REALISED_TARGETS:
        model = db.scalar(
            select(ModelMetric.model)
            .where(ModelMetric.kind == "forecast", ModelMetric.indicator_code == ind, ModelMetric.level == "district")
            .where(ModelMetric.is_selected.is_(True))
            .order_by(ModelMetric.created_at.desc())
            .limit(1)
        )
        if model is None:
            continue
        series = [s for s in load_series(db, ind, "district") if len(s.values) >= 3]
        panel = None
        if model == "gbm_panel":
            panel = GbmPanel().fit_panel([s.values[:-1] for s in series if len(s.values) > GbmPanel.LAGS + 2])
        errs = []
        for s in series:
            hist = Series(s.key, s.years[:-1], s.values[:-1])
            if panel is not None and len(hist.values) >= GbmPanel.min_points:
                yhat = panel.predict_series(hist.values, 1)[0]
            else:
                cls = SINGLE_MODELS.get(model, SINGLE_MODELS["naive_drift"])
                cls = cls if len(hist.values) >= cls.min_points else SINGLE_MODELS["naive_last"]
                yhat = cls().fit(hist.years, hist.values).predict(1)[0]
            if s.values[-1]:
                errs.append(abs(yhat - s.values[-1]) / abs(s.values[-1]) * 100)
        if errs:
            out.append(("prediction_realized_error", {"indicator": ind, "model": model}, float(np.mean(errs))))
    return out


def model_quality(db: Session) -> list[tuple[str, dict, float]]:
    run = db.scalar(select(ModelMetric.run_id).where(ModelMetric.kind == "forecast").order_by(ModelMetric.id.desc()))
    rows = db.execute(
        select(ModelMetric.indicator_code, ModelMetric.level, ModelMetric.model, func.avg(ModelMetric.value))
        .where(ModelMetric.run_id == run, ModelMetric.metric == "smape", ModelMetric.is_selected.is_(True))
        .group_by(ModelMetric.indicator_code, ModelMetric.level, ModelMetric.model)
    ).all()
    return [("model_backtest_smape", {"indicator": i, "level": lv, "model": m}, float(v)) for i, lv, m, v in rows]


def reco_stability(db: Session) -> list[tuple[str, dict, float]]:
    """Re-run fixed reference queries and compare the top-5 with the previous run of the same query."""
    from app.services.recommendations import RecommendRequest, list_business_types, recommend

    out = []
    for bt in list_business_types():
        prev = db.scalar(
            select(Recommendation.top)
            .where(
                Recommendation.business_type == bt.business_type,
                Recommendation.region_soato.is_(None),
                Recommendation.target.is_(None),
                Recommendation.request_id.like("monitor-%"),
            )
            .order_by(Recommendation.created_at.desc())
            .limit(1)
        )
        res = recommend(
            db,
            RecommendRequest(business_type=bt.business_type, limit=10),
            request_id=f"monitor-{datetime.now(UTC):%Y%m%d%H%M%S}",
        )
        top = [r["entity"]["soato"] for r in res["results"][:5]]
        width = np.mean([r["rank_range"][1] - r["rank_range"][0] for r in res["results"][:5]])
        out.append(
            (
                "recommendation_stability_jaccard",
                {"business_type": bt.business_type},
                jaccard(prev[:5], top) if prev else 1.0,
            )
        )
        out.append(("recommendation_rank_width", {"business_type": bt.business_type}, float(width)))
    return out


def main() -> None:
    from app.db.session import get_sessionmaker

    with get_sessionmaker()() as db:
        results = data_quality(db) + feature_drift(db) + realised_error(db) + model_quality(db) + reco_stability(db)
        now = datetime.now(UTC)
        db.execute(
            insert(MonitorMetric),
            [{"name": n, "labels": lbl, "value": v, "created_at": now} for n, lbl, v in results],
        )
        db.commit()
        source = db.scalar(select(DataSource.name).limit(1))
    by: dict[str, list] = {}
    for n, lbl, v in results:
        by.setdefault(n, []).append((lbl, v))
    print(f"monitoring snapshot ({len(results)} metrics, source {source}):")
    for n, items in by.items():
        if n == "data_missing_ratio":
            worst = max(items, key=lambda x: x[1])
            print(f"  {n}: {len(items)} indicators, worst {worst[0]['indicator']} = {worst[1]:.3f}")
            continue
        for lbl, v in items:
            alert = "  ⚠ ALERT" if n == "feature_drift_psi" and v > PSI_ALERT else ""
            if n == "data_quality_check_passed" and v < 1:
                alert = "  ⚠ FAILED"
            print(f"  {n}{json.dumps(lbl, ensure_ascii=False)} = {v:.4g}{alert}")


if __name__ == "__main__":
    main()
