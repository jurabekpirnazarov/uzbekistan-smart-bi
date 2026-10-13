"""Backtest every model, pick the best per target × level, write 1–3 year forecasts (PLAN.md Phase 5).

Usage:  python -m ml.forecasting.train          (or: python manage.py train --local)

Writes: model_metrics (kind=forecast, split=backtest), predictions, and the optional scoring features
forecast_population_growth / forecast_business_growth. Logs to MLflow when it is installed and reachable.
"""

from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.db.models import (  # noqa: E402
    District,
    Feature,
    Indicator,
    ModelMetric,
    Observation,
    Prediction,
    Region,
)
from ml.forecasting.backtest import Series, backtest, interval, metrics, residual_quantiles  # noqa: E402
from ml.forecasting.models import ALL_MODELS, SHORT_SERIES_MODELS, SINGLE_MODELS, GbmPanel  # noqa: E402

TARGETS = [
    "population_total",
    "enterprises_active",
    "enterprises_new",
    "trade_services_volume",
    "food_services_volume",
    "health_services_volume",
    "market_services_volume",
]
LEVELS = ("region", "district")
FORECAST_HORIZON = 3
LOW_CONFIDENCE_POINTS = 8
LOCAL_MLFLOW_URI = "sqlite:///" + (ROOT / ".tools" / "mlflow.db").as_posix()
FORECAST_FEATURES = {"population_total": "forecast_population_growth", "enterprises_active": "forecast_business_growth"}


def load_series(db: Session, indicator: str, level: str) -> list[Series]:
    ind_id = db.scalar(select(Indicator.id).where(Indicator.code == indicator))
    if ind_id is None:
        return []
    if level == "district":
        q = select(Observation.year, Observation.value, District.soato_code).join(
            District, District.id == Observation.district_id
        )
    elif level == "region":
        q = select(Observation.year, Observation.value, Region.soato_code).join(
            Region, Region.id == Observation.region_id
        )
    else:
        q = select(Observation.year, Observation.value, Observation.level)  # soato replaced below
    q = q.where(
        Observation.indicator_id == ind_id,
        Observation.level == level,
        Observation.quarter.is_(None),
        Observation.month.is_(None),
    )
    df = pd.DataFrame(db.execute(q).all(), columns=["year", "value", "soato"])
    if level == "country":
        df["soato"] = "1700"
    out = []
    for soato, g in df.sort_values("year").groupby("soato"):
        out.append(Series(str(soato), g["year"].to_numpy(dtype=int), g["value"].to_numpy(dtype=float)))
    return out


def forecast_one(model: str, s: Series, panel: GbmPanel | None) -> np.ndarray:
    if model == "gbm_panel" and panel is not None and len(s.values) >= GbmPanel.min_points:
        return panel.predict_series(s.values, FORECAST_HORIZON)
    name = model if model != "gbm_panel" else "holt"
    cls = SINGLE_MODELS[name]
    if len(s.values) < cls.min_points:
        cls = SINGLE_MODELS["naive_last"]
    return cls().fit(s.years, s.values).predict(FORECAST_HORIZON)


MIN_EVAL_SHARE = 0.6  # a model must be backtested on >= 60 % of the forecasts the best-covered model has


def select_model(lb: pd.DataFrame) -> str:
    """Lowest mean sMAPE over horizons, among models with comparable backtest coverage.

    Without the coverage rule a model that needs more history (e.g. Holt on a 6-point series) would be
    judged only on the easiest, latest origin and look unfairly good.
    """
    n = lb.groupby("model")["n"].sum()
    eligible = n[n >= MIN_EVAL_SHARE * n.max()].index
    mean = lb[lb["model"].isin(eligible)].groupby("model")["smape"].mean().dropna()
    return str(mean.idxmin()) if len(mean) else "naive_last"


def run(db: Session, run_id: str) -> pd.DataFrame:
    leaderboard = []
    db.execute(delete(Prediction))
    db.execute(delete(Feature).where(Feature.name.in_(list(FORECAST_FEATURES.values()))))
    for indicator in TARGETS:
        best_region_model = None
        region_q = None
        for level in (*LEVELS, "country"):
            series = load_series(db, indicator, level)
            if not series:
                continue
            longest = max(len(s.values) for s in series)
            if level == "country":  # one series: reuse the region-level choice
                best, q, lb = best_region_model or "naive_drift", region_q, None
            else:
                models = ALL_MODELS if longest >= LOW_CONFIDENCE_POINTS else SHORT_SERIES_MODELS
                bt = backtest(series, models)
                lb = metrics(bt)
                base = lb[lb["model"] == "naive_last"].set_index("horizon")["smape"]
                naive = lb["horizon"].map(base)
                lb["improvement_vs_naive_pct"] = (1 - lb["smape"] / naive.where(naive > 0)) * 100
                best = select_model(lb)
                q = residual_quantiles(bt, best)
                if level == "region":
                    best_region_model, region_q = best, q
                lb.insert(0, "level", level)
                lb.insert(0, "indicator", indicator)
                lb["selected"] = lb["model"] == best
                leaderboard.append(lb)
                for r in lb.itertuples(index=False):
                    for metric in ("mae", "rmse", "mape", "smape", "improvement_vs_naive_pct"):
                        val = getattr(r, metric)
                        db.add(
                            ModelMetric(
                                run_id=run_id,
                                kind="forecast",
                                split="backtest",
                                indicator_code=indicator,
                                level=level,
                                model=r.model,
                                horizon=int(r.horizon),
                                metric=metric,
                                value=None if pd.isna(val) else float(val),
                                is_selected=bool(r.selected),
                            )
                        )

            panel = None
            if best == "gbm_panel":
                panel = GbmPanel().fit_panel([s.values for s in series if len(s.values) >= GbmPanel.LAGS + 2])
            q = q or {"q025": -0.1, "q10": -0.05, "q90": 0.05, "q975": 0.1}
            rows = []
            feats = []
            for s in series:
                yhat = np.maximum(forecast_one(best, s, panel), 0.0)
                low = len(s.values) < LOW_CONFIDENCE_POINTS
                origin = int(s.years[-1])
                for h in range(1, FORECAST_HORIZON + 1):
                    lo80, hi80, lo95, hi95 = interval(float(yhat[h - 1]), q, h)
                    rows.append(
                        {
                            "run_id": run_id,
                            "indicator_code": indicator,
                            "level": level,
                            "soato": s.key,
                            "model": best,
                            "origin_year": origin,
                            "year": origin + h,
                            "horizon": h,
                            "yhat": float(yhat[h - 1]),
                            "lo80": max(lo80, 0.0),
                            "hi80": hi80,
                            "lo95": max(lo95, 0.0),
                            "hi95": hi95,
                            "history_points": len(s.values),
                            "low_confidence": low,
                        }
                    )
                if indicator in FORECAST_FEATURES and level != "country" and s.values[-1] > 0:
                    feats.append((s.key, origin, float((yhat[1] / s.values[-1]) ** 0.5 - 1)))
            db.execute(insert(Prediction), rows)
            if feats:
                write_forecast_features(db, FORECAST_FEATURES[indicator], level, feats)
        db.commit()
    return pd.concat(leaderboard, ignore_index=True) if leaderboard else pd.DataFrame()


def write_forecast_features(db: Session, name: str, level: str, feats: list[tuple[str, int, float]]) -> None:
    """Annualised 2-year forecast growth as an optional scoring feature (model prediction, not a statistic)."""
    if level == "district":
        ids = dict(db.execute(select(District.soato_code, District.id)).all())
        reg = dict(db.execute(select(District.soato_code, District.region_id)).all())
    else:
        ids = dict(db.execute(select(Region.soato_code, Region.id)).all())
        reg = ids
    db.execute(
        insert(Feature),
        [
            {
                "name": name,
                "level": level,
                "region_id": reg[k],
                "district_id": ids[k] if level == "district" else None,
                "year": y,
                "value": v,
                "is_synthetic": False,
                "quality_flag": "model_prediction",
                "lineage": {"source": "predictions", "horizon": 2},
                "feature_version": "forecast",
            }
            for k, y, v in feats
            if k in ids
        ],
    )


def log_mlflow(lb: pd.DataFrame, run_id: str) -> str:
    try:
        import mlflow
    except ImportError:
        return "MLflow not installed — metrics are in the model_metrics table."
    from app.core.config import get_settings

    uri = get_settings().mlflow_tracking_uri
    if uri.startswith("http"):
        import requests

        try:
            requests.get(uri.rstrip("/") + "/health", timeout=2).raise_for_status()
        except requests.RequestException:
            uri = LOCAL_MLFLOW_URI  # no tracking server: log to the local store that `mlflow ui` reads
    try:
        mlflow.set_tracking_uri(uri)
        mlflow.set_experiment("forecasting")
        sel = lb[lb["selected"]]
        for (ind, lv), g in sel.groupby(["indicator", "level"]):
            with mlflow.start_run(run_name=f"{ind}-{lv}"):
                mlflow.set_tags(
                    {
                        "run_id": run_id,
                        "indicator": ind,
                        "level": lv,
                        "model": g["model"].iloc[0],
                        "alias": "production",
                    }
                )
                mlflow.log_params({"model": g["model"].iloc[0], "horizons": "1,2", "origins": 3})
                for r in g.itertuples():
                    mlflow.log_metric(f"smape_h{r.horizon}", float(r.smape))
                    mlflow.log_metric(f"mae_h{r.horizon}", float(r.mae))
        return f"Logged to MLflow at {uri}"
    except Exception as e:  # tracking server down → not fatal
        return f"MLflow not reachable ({type(e).__name__}) — metrics are in the model_metrics table."


def main() -> None:
    from app.db.session import get_sessionmaker

    run_id = time.strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:6]
    t0 = time.time()
    with get_sessionmaker()() as db:
        lb = run(db, run_id)
    print(f"forecast run {run_id} finished in {time.time() - t0:.0f}s\n")
    pd.set_option("display.width", 160)
    for (ind, lv), g in lb.groupby(["indicator", "level"], sort=False):
        print(f"== {ind} · {lv}")
        view = g.pivot_table(index="model", columns="horizon", values="smape").round(2)
        view.columns = [f"sMAPE h{c}" for c in view.columns]
        imp = g[g["horizon"] == 1].set_index("model")["improvement_vs_naive_pct"].round(1)
        view["vs naive h1 %"] = imp
        view["selected"] = ["✓" if m == g[g["selected"]]["model"].iloc[0] else "" for m in view.index]
        print(view.to_string(), "\n")
    print(log_mlflow(lb, run_id))


if __name__ == "__main__":
    main()
