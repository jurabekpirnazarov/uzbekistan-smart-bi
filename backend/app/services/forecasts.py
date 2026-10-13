"""Forecasts written by ml/forecasting/train.py, joined with history and backtest quality.

A forecast is a MODEL PREDICTION, never an official statistic (CLAUDE.md rule 5): responses say so.
"""

from __future__ import annotations

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ModelMetric, Prediction
from app.services import statistics as stats

NOTE = "Model prediction based on official history — not an official statistic."


class ForecastPoint(BaseModel):
    year: int
    horizon: int
    yhat: float
    lo80: float | None
    hi80: float | None
    lo95: float | None
    hi95: float | None


class Forecast(BaseModel):
    indicator: str
    level: str
    soato: str
    name: str
    history: list[stats.Point]
    forecast: list[ForecastPoint]
    model: str
    backtest: dict[str, float | None]  # smape_h1, smape_h2, mape_h1, improvement_vs_naive_pct_h1
    history_points: int
    low_confidence: bool
    note: str = NOTE
    meta: stats.Meta


def get_forecast(db: Session, indicator: str, level: str, soato: str, horizon: int = 3) -> Forecast:
    ts = stats.get_timeseries(db, indicator, level, soato)  # type: ignore[arg-type]
    rows = db.scalars(
        select(Prediction)
        .where(
            Prediction.indicator_code == indicator,
            Prediction.level == level,
            Prediction.soato == soato,
            Prediction.horizon <= horizon,
        )
        .order_by(Prediction.horizon)
    ).all()
    if not rows:
        raise stats.NotFoundError(
            f"No forecast for '{indicator}' at {level} {soato}. Forecast targets: population, businesses, "
            "services volumes — run `python manage.py train --local` if none exist."
        )
    model = rows[0].model
    metric_level = "region" if level == "country" else level
    mm = db.execute(
        select(ModelMetric.metric, ModelMetric.horizon, ModelMetric.value).where(
            ModelMetric.kind == "forecast",
            ModelMetric.indicator_code == indicator,
            ModelMetric.level == metric_level,
            ModelMetric.model == model,
            ModelMetric.run_id == db.scalar(select(Prediction.run_id).limit(1)),
        )
    ).all()
    backtest = {f"{m}_h{h}": v for m, h, v in mm if m in ("smape", "mape", "improvement_vs_naive_pct")}
    return Forecast(
        indicator=indicator,
        level=level,
        soato=soato,
        name=ts.name,
        history=ts.points,
        forecast=[
            ForecastPoint(
                year=r.year, horizon=r.horizon, yhat=r.yhat, lo80=r.lo80, hi80=r.hi80, lo95=r.lo95, hi95=r.hi95
            )
            for r in rows
        ],
        model=model,
        backtest=backtest,
        history_points=rows[0].history_points,
        low_confidence=rows[0].low_confidence,
        meta=ts.meta,
    )


def forecast_targets(db: Session) -> list[str]:
    return sorted(set(db.scalars(select(Prediction.indicator_code).distinct()).all()))
