from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from pipelines.load_siat import IndicatorSpec, convert_values, district_kind, load_map

ROOT = Path(__file__).resolve().parents[2]


def spec(mult: float, unit: str, additive: bool = True) -> IndicatorSpec:
    return IndicatorSpec(
        siat_dataset_id=1,
        name_en="x",
        category="c",
        source_unit="s",
        unit=unit,
        unit_multiplier=mult,
        additive=additive,
    )


def test_indicator_map_is_valid_and_has_unique_datasets() -> None:
    m = load_map(ROOT / "data" / "reference" / "indicator_map.yaml")
    assert "population_total" in m.indicators
    ids = [s.siat_dataset_id for s in m.indicators.values()]
    assert len(ids) == len(set(ids))


def test_growth_rates_are_never_additive() -> None:
    m = load_map(ROOT / "data" / "reference" / "indicator_map.yaml")
    for code, s in m.indicators.items():
        if "previous year" in s.unit:
            assert not s.additive, code


def test_duplicate_dataset_in_map_is_rejected(tmp_path: Path) -> None:
    f = tmp_path / "map.yaml"
    entry = "{siat_dataset_id: 5, name_en: a, category: c, source_unit: u, unit: u, unit_multiplier: 1, additive: true}"
    f.write_text(f"indicators:\n  a: {entry}\n  b: {entry}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="mapped twice"):
        load_map(f)


def test_unit_conversion_and_filtering() -> None:
    obs = pd.DataFrame(
        {
            "dataset_id": [246, 4482, 999, 246],
            "level": ["region", "district", "region", "other"],
            "value": [3943.0, 1.5, 7.0, 1.0],
        }
    )
    out = convert_values(
        obs, {246: ("population_total", spec(1000, "persons")), 4482: ("market_services_volume", spec(1e9, "UZS"))}
    )
    assert list(out["indicator_code"]) == ["population_total", "market_services_volume"]
    assert list(out["value"]) == [3_943_000.0, 1_500_000_000.0]
    assert list(out["unit"]) == ["persons", "UZS"]


@pytest.mark.parametrize(
    ("value", "name", "kind"),
    [
        (1.0, "Kuva district", "district"),
        (0.0, "Nukus city", "city"),
        (2.0, "Some city", "city"),
        (None, "Unknown district", "district"),
    ],
)
def test_district_kind(value: float | None, name: str, kind: str) -> None:
    assert district_kind(value, name) == kind
