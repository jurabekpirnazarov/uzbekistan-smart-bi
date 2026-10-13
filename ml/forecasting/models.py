"""Forecasting models for short annual series (PLAN.md Phase 5).

Interface: fit(years, values) → self; predict(horizon) → np.ndarray of length `horizon`.
Prophet is deliberately not used: annual series have only 6–17 points.
"""

from __future__ import annotations

import warnings
from abc import ABC, abstractmethod

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import LinearRegression


class Forecaster(ABC):
    name: str = "base"
    min_points: int = 2

    @abstractmethod
    def fit(self, years: np.ndarray, values: np.ndarray) -> Forecaster: ...

    @abstractmethod
    def predict(self, horizon: int) -> np.ndarray: ...


class NaiveLast(Forecaster):
    """Mandatory baseline: the last observed value."""

    name, min_points = "naive_last", 1

    def fit(self, years: np.ndarray, values: np.ndarray) -> NaiveLast:
        self.last = float(values[-1])
        return self

    def predict(self, horizon: int) -> np.ndarray:
        return np.full(horizon, self.last)


class NaiveDrift(Forecaster):
    """Mandatory baseline: last value + average historical step."""

    name, min_points = "naive_drift", 2

    def fit(self, years: np.ndarray, values: np.ndarray) -> NaiveDrift:
        self.last = float(values[-1])
        self.step = (float(values[-1]) - float(values[0])) / max(len(values) - 1, 1)
        return self

    def predict(self, horizon: int) -> np.ndarray:
        return self.last + self.step * np.arange(1, horizon + 1)


class LinearTrend(Forecaster):
    """Ordinary least squares on year."""

    name, min_points = "linear_trend", 3

    def fit(self, years: np.ndarray, values: np.ndarray) -> LinearTrend:
        self.model = LinearRegression().fit(years.reshape(-1, 1), values)
        self.last_year = int(years[-1])
        return self

    def predict(self, horizon: int) -> np.ndarray:
        future = np.arange(self.last_year + 1, self.last_year + horizon + 1).reshape(-1, 1)
        return self.model.predict(future)


class Holt(Forecaster):
    """Damped additive-trend exponential smoothing (statsmodels); drift fallback if it cannot fit."""

    name, min_points = "holt", 5

    def fit(self, years: np.ndarray, values: np.ndarray) -> Holt:
        from statsmodels.tsa.holtwinters import ExponentialSmoothing

        self.fallback: NaiveDrift | None = None
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                self.res = ExponentialSmoothing(
                    values.astype(float), trend="add", damped_trend=True, initialization_method="estimated"
                ).fit()
        except Exception:
            self.fallback = NaiveDrift().fit(years, values)
        return self

    def predict(self, horizon: int) -> np.ndarray:
        if self.fallback is not None:
            return self.fallback.predict(horizon)
        out = np.asarray(self.res.forecast(horizon), dtype=float)
        return out if np.all(np.isfinite(out)) else np.full(horizon, np.nan)


class GbmPanel:
    """Gradient boosting on lagged growth rates pooled across all entities of one level.

    Predicts next-year growth g_t = y_t / y_{t-1} - 1 from the previous LAGS growth rates; multi-step
    forecasts are recursive. Fit on the panel once per origin (no future data: only years <= origin).
    """

    name, min_points = "gbm_panel", 8
    LAGS = 3

    def fit_panel(self, series: list[np.ndarray]) -> GbmPanel:
        X, y = [], []
        for v in series:
            g = growth_rates(v)
            for t in range(self.LAGS, len(g)):
                X.append(g[t - self.LAGS : t])
                y.append(g[t])
        self.model = None
        if len(y) >= 30:
            self.model = HistGradientBoostingRegressor(max_iter=150, learning_rate=0.05, max_depth=3, random_state=0)
            self.model.fit(np.array(X), np.array(y))
        return self

    def predict_series(self, values: np.ndarray, horizon: int) -> np.ndarray:
        g = list(growth_rates(values))
        if self.model is None or len(g) < self.LAGS:
            return NaiveDrift().fit(np.arange(len(values)), values).predict(horizon)
        level, out = float(values[-1]), []
        for _ in range(horizon):
            nxt = float(self.model.predict(np.array([g[-self.LAGS :]]))[0])
            level *= 1 + nxt
            out.append(level)
            g.append(nxt)
        return np.array(out)


def growth_rates(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        g = v[1:] / v[:-1] - 1
    return np.nan_to_num(g, nan=0.0, posinf=0.0, neginf=0.0)


SINGLE_MODELS: dict[str, type[Forecaster]] = {
    m.name: m
    for m in (NaiveLast, NaiveDrift, LinearTrend, Holt)  # type: ignore[type-abstract]
}
SHORT_SERIES_MODELS = ("naive_last", "naive_drift", "linear_trend", "holt")  # services series (2020+)
ALL_MODELS = (*SHORT_SERIES_MODELS, "gbm_panel")
