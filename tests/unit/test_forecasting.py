from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ml.forecasting import backtest as bt
from ml.forecasting.models import SINGLE_MODELS, GbmPanel, Holt, LinearTrend, NaiveDrift, NaiveLast
from ml.forecasting.train import select_model

YEARS = np.arange(2015, 2025)
VALUES = np.array([100.0, 110, 120, 130, 140, 150, 160, 170, 180, 190])


def test_naive_baselines_by_hand() -> None:
    assert NaiveLast().fit(YEARS, VALUES).predict(2).tolist() == [190, 190]
    assert NaiveDrift().fit(YEARS, VALUES).predict(2).tolist() == [200, 210]  # (190-100)/9 = 10 per year


def test_linear_and_holt_follow_a_linear_trend() -> None:
    assert LinearTrend().fit(YEARS, VALUES).predict(1)[0] == pytest.approx(200)
    assert Holt().fit(YEARS, VALUES).predict(1)[0] == pytest.approx(200, rel=0.02)


def test_backtest_never_uses_future_data(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[int, int]] = []

    class Spy(NaiveLast):
        name = "spy"

        def fit(self, years, values):  # noqa: ANN001, ANN201
            seen.append((int(years[-1]), len(values)))
            return super().fit(years, values)

    monkeypatch.setitem(SINGLE_MODELS, "spy", Spy)
    rows = bt.backtest([bt.Series("X", YEARS, VALUES)], ("spy",))
    for origin_year, n in seen:
        assert n == origin_year - 2015 + 1  # only values up to the origin
    assert set(rows["origin_year"]) == {2021, 2022, 2023}
    assert (rows["origin_year"] + rows["horizon"] <= 2024).all()


def test_gbm_panel_trains_only_on_history_up_to_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    lengths: list[int] = []
    orig = GbmPanel.fit_panel

    def spy(self, series):  # noqa: ANN001, ANN202
        lengths.append(max(len(v) for v in series))
        return orig(self, series)

    monkeypatch.setattr(GbmPanel, "fit_panel", spy)
    series = [bt.Series(str(i), YEARS, VALUES * (1 + i / 10)) for i in range(5)]
    rows = bt.backtest(series, ("gbm_panel",))
    assert lengths == [7, 8, 9]  # origins 2021, 2022, 2023
    assert not rows.empty


def test_metrics_and_intervals() -> None:
    df = pd.DataFrame(
        [("m", "A", 2020, 1, 100.0, 110.0), ("m", "B", 2020, 1, 200.0, 190.0)],
        columns=["model", "key", "origin_year", "horizon", "y", "yhat"],
    )
    m = bt.metrics(df).iloc[0]
    assert m["mae"] == 10 and m["mape"] == pytest.approx(7.5)
    q = {"q025": -0.2, "q10": -0.1, "q90": 0.1, "q975": 0.2}
    for h in (1, 2, 3):
        lo80, hi80, lo95, hi95 = bt.interval(100.0, q, h)
        assert lo95 <= lo80 <= 100.0 <= hi80 <= hi95
    assert bt.interval(100.0, q, 4)[1] - 100 == pytest.approx(2 * (bt.interval(100.0, q, 1)[1] - 100))  # √h widening
    # yhat stays inside even when all residuals are one-sided
    lo80, hi80, *_ = bt.interval(50.0, {"q025": 0.1, "q10": 0.2, "q90": 0.3, "q975": 0.4}, 1)
    assert lo80 <= 50.0 <= hi80


def test_select_model_requires_comparable_coverage() -> None:
    lb = pd.DataFrame(
        [
            ("naive_last", 1, 20.0, 100),
            ("naive_last", 2, 30.0, 80),
            ("holt", 1, 5.0, 20),  # judged on far fewer forecasts → not eligible
            ("naive_drift", 1, 15.0, 100),
            ("naive_drift", 2, 25.0, 80),
        ],
        columns=["model", "horizon", "smape", "n"],
    )
    assert select_model(lb) == "naive_drift"
