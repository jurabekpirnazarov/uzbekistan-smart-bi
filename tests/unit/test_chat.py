from __future__ import annotations

import pytest

from app.services import chat
from app.services import statistics as stats


@pytest.mark.parametrize(
    ("text", "lang"),
    [
        ("Which 5 regions grew fastest in operating businesses since 2020?", "en"),
        ("Farg‘ona viloyatida qaysi tumanlarda aholi eng tez o‘smoqda?", "uz"),
        ("Toshkent viloyatida dorixona ochish uchun eng yaxshi tuman qaysi?", "uz"),
        ("Где в Самаркандской области лучше открыть кафе?", "ru"),
    ],
)
def test_detect_language(text: str, lang: str) -> None:
    assert chat.detect_language(text) == lang


def _ranking(year: int, values: dict[str, float]) -> stats.Ranking:
    items = [stats.RankingItem(rank=i, soato=s, name=s, value=v) for i, (s, v) in enumerate(values.items(), 1)]
    return stats.Ranking(
        level="region", year=year, years_available=[2025, 2020], items=items, total=None, meta=stats.Meta()
    )


def test_growth_ranking_is_computed_in_python(monkeypatch: pytest.MonkeyPatch) -> None:
    data = {2020: {"A": 100.0, "B": 200.0, "C": 50.0}, 2025: {"A": 150.0, "B": 220.0, "C": 100.0}}
    monkeypatch.setattr(
        stats, "get_ranking", lambda db, ind, lv, year=None, region=None: _ranking(year or 2025, data[year or 2025])
    )
    out = chat.tool_get_growth_ranking(None, "x", "region", 2020)  # type: ignore[arg-type]
    assert [r["soato"] for r in out["items"]] == ["C", "A", "B"]  # +100%, +50%, +10%
    assert out["items"][0]["pct_change"] == 100.0
    assert out["items"][0]["cagr_pct"] == round((2 ** (1 / 5) - 1) * 100, 2)
    assert out["year_to"] == 2025


def test_compute_change_reports_missing_year(monkeypatch: pytest.MonkeyPatch) -> None:
    ts = stats.TimeSeries(
        level="region", soato="1", name="R", points=[stats.Point(year=2024, value=10.0)], meta=stats.Meta()
    )
    monkeypatch.setattr(stats, "get_timeseries", lambda *a, **k: ts)
    out = chat.tool_compute_change(None, "x", "region", "1", 2019)  # type: ignore[arg-type]
    assert out["error"] == "year not available"


def test_unknown_tool_is_reported_not_raised() -> None:
    assert chat.run_tool(None, "nope", {})["error"].startswith("unknown tool")  # type: ignore[arg-type]
