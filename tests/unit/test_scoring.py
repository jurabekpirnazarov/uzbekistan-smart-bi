from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from ml.scoring import engine
from ml.scoring.profiles import Profile, load_profile_file, load_profiles, load_targets


def make_profile(**over) -> Profile:  # noqa: ANN003
    base = {
        "business_type": "test_shop",
        "display_name": {"en": "Test shop", "uz": "Do‘kon", "ru": "Магазин"},
        "min_budget_uzs": 100,
        "factors": [
            {"feature": "population", "weight": 0.6, "direction": "+", "label": "Population"},
            {"feature": "business_density", "weight": 0.4, "direction": "-", "label": "Low competition"},
        ],
    }
    return Profile.model_validate(base | over)


def data(missing: dict[str, list[str]] | None = None) -> engine.ScoringInput:
    ents = pd.DataFrame(
        [
            {"soato": s, "name": s, "level": "district", "region_soato": "R", "kind": "district", "geom_approx": False}
            for s in "ABCD"
        ]
    )
    feats = []
    pops = {"A": 400, "B": 300, "C": 200, "D": 100}
    dens = {"A": 40, "B": 10, "C": 20, "D": 30}
    for s in "ABCD":
        if s not in (missing or {}).get("population", []):
            feats.append({"soato": s, "feature": "population", "year": 2025, "value": pops[s], "is_synthetic": False})
        if s not in (missing or {}).get("business_density", []):
            feats.append(
                {"soato": s, "feature": "business_density", "year": 2025, "value": dens[s], "is_synthetic": False}
            )
        feats.append({"soato": s, "feature": "population", "year": 2020, "value": 1, "is_synthetic": False})
    return engine.ScoringInput(ents, pd.DataFrame(feats), {"population": [{"dataset_id": 246, "url": "u"}]})


def test_contributions_sum_exactly_to_score() -> None:
    out = engine.score(data(), make_profile())
    for r in out["results"]:
        assert round(sum(b["contribution"] for b in r["breakdown"]), 2) == r["score"]
    assert out["years_used"]["population"] == 2025  # latest year, not 2020
    # A: population 100th pct (×0.6) + highest density → 0 after inversion
    a = next(r for r in out["results"] if r["entity"]["soato"] == "A")
    assert a["score"] == pytest.approx(60.0)


def test_weights_override_changes_ranking() -> None:
    base = engine.score(data(), make_profile())
    over = engine.score(data(), make_profile(), weights_override={"population": 1.0, "business_density": 0.0})
    assert base["results"][0]["entity"]["soato"] == "B"  # 0.6·66.7 + 0.4·100 (lowest density)
    assert over["results"][0]["entity"]["soato"] == "A"  # population only
    with pytest.raises(ValueError):
        engine.score(data(), make_profile(), weights_override={"unknown": 1.0})


def test_low_coverage_entities_are_excluded_and_reported() -> None:
    out = engine.score(data({"population": ["C"]}), make_profile())
    assert "C" not in [r["entity"]["soato"] for r in out["results"]]
    ex = out["excluded_insufficient_data"][0]
    assert ex["entity"]["soato"] == "C" and ex["coverage"] == 0.4 and ex["missing_features"] == ["population"]


def test_partial_coverage_renormalises_with_warning() -> None:
    out = engine.score(
        data({"business_density": ["D"]}),
        make_profile(
            factors=[
                {"feature": "population", "weight": 0.8, "direction": "+", "label": "Population"},
                {"feature": "business_density", "weight": 0.2, "direction": "-", "label": "Low competition"},
            ]
        ),
    )
    d = next(r for r in out["results"] if r["entity"]["soato"] == "D")
    assert d["coverage"] == 0.8 and d["warnings"]
    assert round(sum(b["contribution"] for b in d["breakdown"]), 2) == d["score"]


def test_stability_is_deterministic_with_fixed_seed() -> None:
    a = engine.score(data(), make_profile(), seed=7)
    b = engine.score(data(), make_profile(), seed=7)
    assert [r["rank_range"] for r in a["results"]] == [r["rank_range"] for r in b["results"]]
    for r in a["results"]:
        assert r["rank_range"][0] <= r["rank"] <= r["rank_range"][1] or r["rank_range"][0] <= r["rank_range"][1]


def test_budget_warning_and_targets() -> None:
    out = engine.score(data(), make_profile(), budget_uzs=50)
    assert out["budget_warning"] and all(any("Budget" in w for w in r["warnings"]) for r in out["results"])
    w = engine.resolve_weights(make_profile(), target="low_competition", targets=load_targets())
    weights = {f.feature: wt for f, wt in w}
    assert weights["business_density"] > 0.4 and sum(weights.values()) == pytest.approx(1.0)


def test_profile_validation() -> None:
    with pytest.raises(ValueError):
        make_profile(factors=[{"feature": "population", "weight": 0.5, "label": "x"}])  # weights ≠ 1


def test_new_yaml_profile_needs_no_code(tmp_path: Path) -> None:
    (tmp_path / "kiosk.yaml").write_text(
        "business_type: kiosk\n"
        "display_name: {en: Kiosk, uz: Kiosk, ru: Киоск}\n"
        "min_budget_uzs: 10\n"
        "factors:\n"
        "  - {feature: population, weight: 1.0, direction: '+', label: People}\n",
        encoding="utf-8",
    )
    p = load_profile_file(tmp_path / "kiosk.yaml")
    out = engine.score(data(), p)
    assert out["business_type"] == "kiosk" and out["results"][0]["entity"]["soato"] == "A"


def test_shipped_profiles_are_valid() -> None:
    profiles = load_profiles()
    assert len(profiles) == 11
    assert {"bakery", "pharmacy", "agri_business"} <= set(profiles)
