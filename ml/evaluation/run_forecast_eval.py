"""Forecast evaluation: the backtest leaderboard of the latest training run (PLAN.md Phase 5 / 11)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ModelMetric


def run(db: Session) -> dict:
    run_id = db.scalar(select(ModelMetric.run_id).where(ModelMetric.kind == "forecast").order_by(ModelMetric.id.desc()))
    if run_id is None:
        return {"run_id": None, "rows": []}
    rows = db.execute(
        select(
            ModelMetric.indicator_code,
            ModelMetric.level,
            ModelMetric.model,
            ModelMetric.horizon,
            ModelMetric.metric,
            ModelMetric.value,
            ModelMetric.is_selected,
        ).where(ModelMetric.run_id == run_id, ModelMetric.kind == "forecast")
    ).all()
    board: dict[tuple, dict] = {}
    for ind, lv, model, h, metric, value, sel in rows:
        r = board.setdefault((ind, lv, model), {"indicator": ind, "level": lv, "model": model, "selected": sel})
        r[f"{metric}_h{h}"] = value
    return {"run_id": run_id, "rows": sorted(board.values(), key=lambda r: (r["indicator"], r["level"], r["model"]))}
