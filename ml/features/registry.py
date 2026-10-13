"""Feature types as pure functions over a panel of official observations (PLAN.md Phase 3).

The panel is indexed by (level, region_id, district_id, year); region/district ids use -1 for "none".
Every feature function returns a FeatureResult: the values plus the input columns it used, so the
pipeline can derive lineage (observation ids) and the synthetic flag generically.
Missing inputs produce NaN — values are never imputed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

INDEX = ["level", "region_id", "district_id", "year"]
NONE_ID = -1


@dataclass
class Col:
    """One input column aligned to the panel index."""

    code: str
    values: pd.Series
    ids: pd.Series
    synthetic: pd.Series
    available: bool = True  # False when the indicator does not exist in the warehouse at all


@dataclass
class FeatureResult:
    values: pd.Series
    inputs: list[Col] = field(default_factory=list)


class Panel:
    """Wide view of annual observations with lag and region-broadcast lookups."""

    def __init__(self, obs: pd.DataFrame, district_kinds: dict[int, str] | None = None) -> None:
        """obs columns: level, region_id, district_id, year, indicator, value, obs_id, is_synthetic."""
        df = obs.copy()
        df["region_id"] = df["region_id"].fillna(NONE_ID).astype(int)
        df["district_id"] = df["district_id"].fillna(NONE_ID).astype(int)
        df["year"] = df["year"].astype(int)
        self.values = df.pivot_table(index=INDEX, columns="indicator", values="value", aggfunc="first")
        self.ids = df.pivot_table(index=INDEX, columns="indicator", values="obs_id", aggfunc="first")
        self.synth = df.pivot_table(index=INDEX, columns="indicator", values="is_synthetic", aggfunc="max")
        self.index: pd.MultiIndex = self.values.index  # type: ignore[assignment]
        self.district_kinds = district_kinds or {}

    @property
    def indicators(self) -> set[str]:
        return set(self.values.columns)

    def _keys(self, lag: int, scope: str) -> pd.MultiIndex:
        lv = self.index.get_level_values("level")
        rid = self.index.get_level_values("region_id")
        did = self.index.get_level_values("district_id")
        yr = self.index.get_level_values("year") - lag
        if scope == "region":  # districts read their region's row; regions/country read their own
            is_d = lv == "district"
            lv = np.where(is_d, "region", lv)
            did = np.where(is_d, NONE_ID, did)
        return pd.MultiIndex.from_arrays([lv, rid, did, yr], names=INDEX)

    def get(self, code: str, lag: int = 0, scope: str = "self") -> Col:
        if code not in self.values.columns:
            nan = pd.Series(np.nan, index=self.index)
            return Col(code, nan, nan, pd.Series(False, index=self.index), available=False)
        keys = self._keys(lag, scope)

        def look(frame: pd.DataFrame) -> pd.Series:
            return pd.Series(frame[code].reindex(keys).to_numpy(), index=self.index)

        synth = look(self.synth).fillna(0).astype(bool)
        return Col(code, look(self.values).astype(float), look(self.ids), synth)


def _safe_div(a: pd.Series, b: pd.Series) -> pd.Series:
    out = a / b.where(b != 0)
    return out.replace([np.inf, -np.inf], np.nan)


# --- feature types --------------------------------------------------------------------------


def passthrough(p: Panel, spec: dict) -> FeatureResult:
    c = p.get(spec["indicator"])
    return FeatureResult(c.values, [c])


def growth(p: Panel, spec: dict) -> FeatureResult:
    """v_t / v_{t-lag} - 1"""
    lag = int(spec.get("lag", 1))
    now, before = p.get(spec["indicator"]), p.get(spec["indicator"], lag)
    return FeatureResult(_safe_div(now.values, before.values) - 1, [now, before])


def cagr(p: Panel, spec: dict) -> FeatureResult:
    """(v_t / v_{t-years})^(1/years) - 1, only for positive values."""
    n = int(spec["years"])
    now, before = p.get(spec["indicator"]), p.get(spec["indicator"], n)
    ratio = _safe_div(now.values, before.values).where((now.values > 0) & (before.values > 0))
    return FeatureResult(ratio ** (1 / n) - 1, [now, before])


def ratio(p: Panel, spec: dict) -> FeatureResult:
    num, den = p.get(spec["num"]), p.get(spec["den"])
    return FeatureResult(_safe_div(num.values, den.values), [num, den])


def per_capita(p: Panel, spec: dict) -> FeatureResult:
    """num / population * per (per=1 → per person, 1000 → per 1,000 people)."""
    num, pop = p.get(spec["num"]), p.get(spec.get("den", "population_total"))
    return FeatureResult(_safe_div(num.values, pop.values) * float(spec.get("per", 1)), [num, pop])


def index_to_rate(p: Panel, spec: dict) -> FeatureResult:
    """'% of previous year' index → growth rate: 112.3 → 0.123."""
    c = p.get(spec["indicator"])
    return FeatureResult(index_value_to_rate(c.values), [c])


def index_value_to_rate(v: pd.Series | float) -> pd.Series | float:
    return v / 100.0 - 1.0


def region_context(p: Panel, spec: dict) -> FeatureResult:
    """Region-level value broadcast to all districts of the region (never presented as a district fact)."""
    if "indicator" in spec:
        c = p.get(spec["indicator"], scope="region")
        return FeatureResult(c.values, [c])
    num, den = p.get(spec["num"], scope="region"), p.get(spec["den"], scope="region")
    return FeatureResult(_safe_div(num.values, den.values), [num, den])


def reference(p: Panel, spec: dict) -> FeatureResult:
    """Attribute of the territory itself, e.g. districts.kind == city → 1.0 / 0.0 (districts only)."""
    if spec["field"] != "districts.kind":
        raise ValueError(f"unsupported reference field {spec['field']}")
    did = p.index.get_level_values("district_id")
    lv = p.index.get_level_values("level")
    vals = [
        (1.0 if p.district_kinds.get(int(d)) == spec["equals"] else 0.0) if level == "district" else np.nan
        for level, d in zip(lv, did, strict=True)
    ]
    return FeatureResult(pd.Series(vals, index=p.index, dtype=float), [])


FEATURE_TYPES: dict[str, Callable[[Panel, dict], FeatureResult]] = {
    "passthrough": passthrough,
    "growth": growth,
    "cagr": cagr,
    "ratio": ratio,
    "per_capita": per_capita,
    "index_to_rate": index_to_rate,
    "region_context": region_context,
    "reference": reference,
}


def input_codes(spec: dict) -> list[str]:
    """Indicator codes a feature spec depends on."""
    codes = [spec[k] for k in ("indicator", "num", "den") if k in spec]
    if spec["type"] == "per_capita" and "den" not in spec:
        codes.append("population_total")
    return codes
