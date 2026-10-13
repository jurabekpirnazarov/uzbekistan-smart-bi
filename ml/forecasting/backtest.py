"""Rolling-origin backtest without leakage (PLAN.md Phase 5).

For each series the last N_ORIGINS years that still have a future observation are forecast origins;
models only ever see values up to and including the origin year.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ml.forecasting.models import SINGLE_MODELS, GbmPanel

N_ORIGINS = 3
HORIZONS = (1, 2)


@dataclass
class Series:
    key: str  # soato
    years: np.ndarray
    values: np.ndarray


def origins_for(years: np.ndarray, n_origins: int = N_ORIGINS) -> list[int]:
    """Indices of origin years: the last n years that have at least one later observation."""
    return list(range(max(0, len(years) - 1 - n_origins), len(years) - 1))


def backtest(series: list[Series], models: tuple[str, ...], horizons: tuple[int, ...] = HORIZONS) -> pd.DataFrame:
    """Rows: model, key, origin_year, horizon, y, yhat."""
    rows = []
    hmax = max(horizons)
    for s in series:
        for k in origins_for(s.years):
            ty, tv = s.years[: k + 1], s.values[: k + 1]
            for name in models:
                if name == "gbm_panel":
                    continue
                cls = SINGLE_MODELS[name]
                if len(tv) < cls.min_points:
                    continue
                yhat = cls().fit(ty, tv).predict(hmax)
                rows += _rows(name, s, k, yhat, horizons)
    if "gbm_panel" in models:
        rows += _backtest_panel(series, horizons)
    return pd.DataFrame(rows, columns=["model", "key", "origin_year", "horizon", "y", "yhat"])


def _rows(name: str, s: Series, k: int, yhat: np.ndarray, horizons: tuple[int, ...]) -> list[tuple]:
    out = []
    for h in horizons:
        j = k + h
        if j < len(s.years) and s.years[j] == s.years[k] + h:
            out.append((name, s.key, int(s.years[k]), h, float(s.values[j]), float(yhat[h - 1])))
    return out


def _backtest_panel(series: list[Series], horizons: tuple[int, ...]) -> list[tuple]:
    rows: list[tuple] = []
    eligible = [s for s in series if len(s.values) >= GbmPanel.min_points]
    if not eligible:
        return rows
    origin_years = sorted({int(s.years[k]) for s in eligible for k in origins_for(s.years)})
    for oy in origin_years:
        train = [s.values[s.years <= oy] for s in eligible]
        model = GbmPanel().fit_panel([v for v in train if len(v) >= GbmPanel.LAGS + 2])
        for s in eligible:
            idx = np.flatnonzero(s.years == oy)
            if not len(idx) or idx[0] + 1 >= len(s.years) or idx[0] + 1 < GbmPanel.min_points:
                continue
            k = int(idx[0])
            yhat = model.predict_series(s.values[: k + 1], max(horizons))
            rows += _rows("gbm_panel", s, k, yhat, horizons)
    return rows


def metrics(df: pd.DataFrame) -> pd.DataFrame:
    """MAE, RMSE, MAPE %, sMAPE % per model × horizon."""
    d = df.dropna(subset=["yhat"]).copy()
    d["err"] = d["yhat"] - d["y"]
    d["ape"] = (d["err"].abs() / d["y"].abs().where(d["y"] != 0)) * 100
    denom = (d["y"].abs() + d["yhat"].abs()).where(lambda x: x != 0)
    d["sape"] = 200 * d["err"].abs() / denom
    g = d.groupby(["model", "horizon"])
    return pd.DataFrame(
        {
            "mae": g["err"].apply(lambda e: e.abs().mean()),
            "rmse": g["err"].apply(lambda e: float(np.sqrt((e**2).mean()))),
            "mape": g["ape"].mean(),
            "smape": g["sape"].mean(),
            "n": g.size(),
        }
    ).reset_index()


def residual_quantiles(df: pd.DataFrame, model: str) -> dict[str, float]:
    """Empirical relative-error quantiles of the horizon-1 backtest (for 80 % and 95 % intervals)."""
    d = df[(df["model"] == model) & (df["horizon"] == 1)].dropna(subset=["yhat"])
    d = d[d["yhat"] != 0]
    rel = ((d["y"] - d["yhat"]) / d["yhat"].abs()).to_numpy()
    if len(rel) < 5:
        return {"q025": -0.1, "q10": -0.05, "q90": 0.05, "q975": 0.1}
    q = np.quantile(rel, [0.025, 0.10, 0.90, 0.975])
    return {"q025": float(q[0]), "q10": float(q[1]), "q90": float(q[2]), "q975": float(q[3])}


def interval(yhat: float, q: dict[str, float], horizon: int) -> tuple[float, float, float, float]:
    """lo80, hi80, lo95, hi95 — residual quantiles widened by √horizon; always contains yhat."""
    s = np.sqrt(horizon)
    base = abs(yhat)
    lo80 = yhat + min(q["q10"], 0) * s * base
    hi80 = yhat + max(q["q90"], 0) * s * base
    lo95 = yhat + min(q["q025"], q["q10"], 0) * s * base
    hi95 = yhat + max(q["q975"], q["q90"], 0) * s * base
    return lo80, hi80, lo95, hi95
