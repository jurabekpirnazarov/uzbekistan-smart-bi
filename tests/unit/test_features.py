from __future__ import annotations

import math

import pandas as pd
import pytest

from ml.features.pipeline import compute_features, load_definitions
from ml.features.registry import FEATURE_TYPES, Panel, index_value_to_rate, input_codes


def obs_frame(rows: list[tuple]) -> pd.DataFrame:
    """rows: (level, region_id, district_id, year, indicator, value[, synthetic])"""
    out = []
    for i, r in enumerate(rows, 1):
        level, rid, did, year, ind, val = r[:6]
        out.append(
            {
                "level": level,
                "region_id": rid,
                "district_id": did,
                "year": year,
                "indicator": ind,
                "value": val,
                "obs_id": i,
                "is_synthetic": r[6] if len(r) > 6 else False,
            }
        )
    return pd.DataFrame(out)


@pytest.fixture
def panel() -> Panel:
    rows = [
        # region 1 and its district 10 (a city) and district 11
        ("region", 1, None, 2023, "population_total", 1000.0),
        ("region", 1, None, 2024, "population_total", 1100.0),
        ("region", 1, None, 2024, "small_business_share_gva", 55.0),
        ("district", 1, 10, 2019, "population_total", 400.0),
        ("district", 1, 10, 2023, "population_total", 500.0),
        ("district", 1, 10, 2024, "population_total", 550.0),
        ("district", 1, 10, 2024, "population_urban", 440.0),
        ("district", 1, 10, 2024, "enterprises_active", 11.0),
        ("district", 1, 10, 2024, "trade_services_growth", 112.3),
        ("district", 1, 11, 2024, "population_total", 0.0),
        ("district", 1, 11, 2024, "enterprises_active", 5.0, True),
    ]
    return Panel(obs_frame(rows), district_kinds={10: "city", 11: "district"})


def value(res, level: str, rid: int, did: int, year: int) -> float:  # noqa: ANN001
    return float(res.values.loc[(level, rid, did, year)])


def test_index_to_rate() -> None:
    assert index_value_to_rate(112.3) == pytest.approx(0.123)
    assert index_value_to_rate(100.0) == 0.0


def test_passthrough_growth_cagr(panel: Panel) -> None:
    assert value(FEATURE_TYPES["passthrough"](panel, {"indicator": "population_total"}), "district", 1, 10, 2024) == 550
    g = FEATURE_TYPES["growth"](panel, {"indicator": "population_total", "lag": 1})
    assert value(g, "district", 1, 10, 2024) == pytest.approx(0.1)
    c = FEATURE_TYPES["cagr"](panel, {"indicator": "population_total", "years": 5})
    assert value(c, "district", 1, 10, 2024) == pytest.approx((550 / 400) ** (1 / 5) - 1)


def test_ratio_per_capita_index(panel: Panel) -> None:
    r = FEATURE_TYPES["ratio"](panel, {"num": "population_urban", "den": "population_total"})
    assert value(r, "district", 1, 10, 2024) == pytest.approx(0.8)
    pc = FEATURE_TYPES["per_capita"](panel, {"num": "enterprises_active", "per": 1000})
    assert value(pc, "district", 1, 10, 2024) == pytest.approx(20.0)
    ix = FEATURE_TYPES["index_to_rate"](panel, {"indicator": "trade_services_growth"})
    assert value(ix, "district", 1, 10, 2024) == pytest.approx(0.123)


def test_region_context_is_broadcast_to_districts(panel: Panel) -> None:
    rc = FEATURE_TYPES["region_context"](panel, {"indicator": "small_business_share_gva"})
    assert value(rc, "district", 1, 10, 2024) == 55.0
    assert value(rc, "district", 1, 11, 2024) == 55.0


def test_reference_is_city(panel: Panel) -> None:
    ref = FEATURE_TYPES["reference"](panel, {"field": "districts.kind", "equals": "city"})
    assert value(ref, "district", 1, 10, 2024) == 1.0
    assert value(ref, "district", 1, 11, 2024) == 0.0
    assert math.isnan(value(ref, "region", 1, -1, 2024))


def test_missing_inputs_and_division_by_zero_are_nan(panel: Panel) -> None:
    pc = FEATURE_TYPES["per_capita"](panel, {"num": "enterprises_active", "per": 1000})
    assert math.isnan(value(pc, "district", 1, 11, 2024))  # population 0 → no division
    g = FEATURE_TYPES["growth"](panel, {"indicator": "population_total", "lag": 1})
    assert math.isnan(value(g, "district", 1, 10, 2019))  # no 2018 value
    missing = FEATURE_TYPES["passthrough"](panel, {"indicator": "does_not_exist"})
    assert missing.values.isna().all()


def test_pipeline_flags_lineage_and_synthetic(panel: Panel) -> None:
    defs = {
        "business_density": {"type": "per_capita", "num": "enterprises_active", "per": 1000},
        "population": {"type": "passthrough", "indicator": "population_total"},
    }
    df = compute_features(panel, defs)
    d11 = df[(df.name == "business_density") & (df.district_id == 11)].iloc[0]
    assert d11.value is None and d11.quality_flag == "invalid_math"
    assert bool(d11.is_synthetic) is True  # synthetic input propagates
    d10 = df[(df.name == "business_density") & (df.district_id == 10) & (df.year == 2024)].iloc[0]
    assert d10.value == pytest.approx(20.0) and not d10.is_synthetic
    assert len(d10.lineage["observation_ids"]) == 2


def test_definitions_file_is_valid() -> None:
    defs = load_definitions()
    assert "population" in defs and "is_city" in defs
    assert input_codes({"type": "per_capita", "num": "x"}) == ["x", "population_total"]
