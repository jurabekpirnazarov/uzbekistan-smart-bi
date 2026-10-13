from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import yaml

from pipelines.discover import eligibility, infer_category, infer_unit
from pipelines.load_siat import load_map


@pytest.mark.parametrize(
    ("unit", "name", "expected"),
    [
        ("thousand people", "Population", ("persons", 1000.0, True)),
        ("in bln. Soums", "Volume of services", ("UZS", 1e9, True)),
        ("at current prices, billion soums", "GRP", ("UZS", 1e9, True)),
        ("in thsd. Soums", "Services per capita", ("UZS", 1e3, False)),
        ("as a percentage of the previous year", "Growth", ("as a percentage of the previous year", 1.0, False)),
        ("units", "Number of enterprises", ("units", 1.0, True)),
        ("Quantity", "Hospitals", ("units", 1.0, True)),
        ("tons", "Harvest", None),  # unknown unit → never guessed
    ],
)
def test_infer_unit(unit: str, name: str, expected: tuple | None) -> None:
    assert infer_unit(unit, name) == expected


def test_infer_category() -> None:
    assert infer_category("Social statistics > Demography > Births") == "population"
    assert infer_category("Economic statistics > Services > Trade") == "services"
    assert infer_category("Economic statistics > Industry") == "economy"


def rows(**over) -> pd.DataFrame:  # noqa: ANN003
    base = {
        "freq": ["A", "A", "A", "A"],
        "level": ["region", "region", "district", "district"],
        "soato_code": ["1730", "1730", "1730401", "1730401"],
        "year": [2023, 2024, 2023, 2024],
        "dimensions": [None, None, None, None],
        "value": [1.0, 2.0, 3.0, 4.0],
    }
    return pd.DataFrame(base | over)


def test_eligibility_accepts_simple_territorial_series() -> None:
    assert eligibility(rows()) is None


@pytest.mark.parametrize(
    ("over", "reason"),
    [
        ({"freq": ["Q"] * 4}, "not annual"),
        ({"level": ["country"] * 4}, "no region or district breakdown"),
        ({"dimensions": ["sex=male", None, None, None]}, "has extra breakdown dimensions"),
        ({"year": [2024] * 4, "soato_code": ["1", "2", "3", "4"]}, "fewer than 2 years"),
    ],
)
def test_eligibility_rejects_unsafe_datasets(over: dict, reason: str) -> None:
    assert eligibility(rows(**over)).startswith(reason)


def spec(i: int, **over) -> dict:  # noqa: ANN003
    base = {"siat_dataset_id": i, "name_en": f"D{i}", "category": "economy", "source_unit": "units"}
    return base | {"unit": "units", "unit_multiplier": 1, "additive": True} | over


def test_auto_map_is_merged_but_curated_entries_win(tmp_path: Path) -> None:
    curated = {"indicators": {"population_total": spec(246, unit="persons", unit_multiplier=1000)}}
    auto = {"indicators": {"siat_9001": spec(9001, auto_added=True), "siat_246": spec(246)}}
    (tmp_path / "indicator_map.yaml").write_text(yaml.safe_dump(curated), encoding="utf-8")
    (tmp_path / "indicator_map.auto.yaml").write_text(yaml.safe_dump(auto), encoding="utf-8")
    m = load_map(tmp_path / "indicator_map.yaml")
    assert set(m.indicators) == {"population_total", "siat_9001"}  # duplicate of a curated dataset ignored
    assert m.indicators["siat_9001"].auto_added and not m.indicators["population_total"].auto_added
