"""Business Opportunity Score (PLAN.md Phase 4). Pure Python — no LLM, no database.

score = Σ wᵢ·xᵢ over the factors that have data, with weights renormalised by coverage, so the
contributions always sum exactly to the score. xᵢ is the factor normalised to 0–100 within the scope
(inverted for direction "-"). Entities with coverage < MIN_COVERAGE are excluded, not ranked.
Stability: Monte Carlo over Dirichlet-perturbed weights (≈ ±20 %) → p10–p90 rank range.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ml.scoring.profiles import Factor, Profile, Targets

MIN_COVERAGE = 0.7
N_DRAWS = 200
DIRICHLET_CONCENTRATION = 100.0  # sd/w ≈ sqrt((1-w)/(w·(K+1))) → ≈ ±20 % for typical weights
MIN_YEAR_SHARE = 0.5  # a feature year is "available" if at least half of the entities have it
DISCLAIMER = (
    "Business Opportunity Score is an analytical model based on available official statistics. "
    "It is decision support, not a guarantee."
)


@dataclass
class ScoringInput:
    """entities: soato, name, level, region_soato, kind, geom_approx (one row per candidate).
    features: soato, feature, year, value, is_synthetic (long format, any years)."""

    entities: pd.DataFrame
    features: pd.DataFrame
    sources: dict[str, list[dict]]  # feature -> [{dataset_id, url, indicator}]


def resolve_weights(
    profile: Profile,
    weights_override: dict[str, float] | None = None,
    target: str | None = None,
    targets: Targets | None = None,
) -> list[tuple[Factor, float]]:
    factors = profile.active_factors()
    weights = {f.feature: f.weight for f in factors}
    if weights_override:
        unknown = set(weights_override) - set(weights)
        if unknown:
            raise ValueError(f"weights_override has features not in the profile: {sorted(unknown)}")
        weights.update({k: float(v) for k, v in weights_override.items()})
    if target:
        if targets is None or target not in targets.targets:
            raise ValueError(f"unknown target '{target}'")
        mult = targets.targets[target]
        weights = {k: w * mult.get(targets.feature_tags.get(k, ""), 1.0) for k, w in weights.items()}
    weights = {k: max(w, 0.0) for k, w in weights.items()}
    total = sum(weights.values())
    if total <= 0:
        raise ValueError("all weights are zero")
    return [(f, weights[f.feature] / total) for f in factors]


def pick_year(feature_rows: pd.DataFrame, n_entities: int) -> int | None:
    """Latest year in which at least MIN_YEAR_SHARE of the entities have a value."""
    ok = feature_rows[feature_rows["value"].notna()]
    if ok.empty:
        return None
    counts = ok.groupby("year")["soato"].nunique()
    good = counts[counts >= max(1, MIN_YEAR_SHARE * n_entities)]
    return int(good.index.max()) if len(good) else int(counts.idxmax())


def normalise(values: pd.Series, method: str, direction: str) -> pd.Series:
    """0–100 within the scope; NaN stays NaN."""
    v = values.astype(float)
    ok = v.dropna()
    if ok.empty:
        return v
    if method == "minmax_winsorized":
        lo, hi = ok.quantile(0.05), ok.quantile(0.95)
        c = v.clip(lo, hi)
        x = (c - lo) / (hi - lo) * 100 if hi > lo else c * 0 + 50.0
    else:  # percentile rank, lowest = 0, highest = 100
        n = len(ok)
        x = (v.rank(method="average") - 1) / (n - 1) * 100 if n > 1 else v * 0 + 50.0
    return 100 - x if direction == "-" else x


def score(
    data: ScoringInput,
    profile: Profile,
    weights_override: dict[str, float] | None = None,
    target: str | None = None,
    targets: Targets | None = None,
    budget_uzs: int | None = None,
    seed: int = 42,
    n_draws: int = N_DRAWS,
) -> dict:
    ents = data.entities.reset_index(drop=True)
    n = len(ents)
    factors = resolve_weights(profile, weights_override, target, targets)

    raw = pd.DataFrame(index=ents["soato"])
    years: dict[str, int | None] = {}
    synth = pd.DataFrame(False, index=ents["soato"], columns=[f.feature for f, _ in factors])
    for f, _ in factors:
        rows = data.features[data.features["feature"] == f.feature]
        y = pick_year(rows, n)
        years[f.feature] = y
        sel = rows[rows["year"] == y].drop_duplicates("soato").set_index("soato") if y is not None else rows.iloc[:0]
        raw[f.feature] = sel["value"].reindex(ents["soato"]).astype(float).to_numpy()
        if "is_synthetic" in sel:
            synth[f.feature] = sel["is_synthetic"].reindex(ents["soato"]).fillna(False).astype(bool).to_numpy()

    norm = pd.DataFrame(
        {f.feature: normalise(raw[f.feature], profile.normalization, f.direction) for f, _ in factors},
        index=raw.index,
    )
    w = np.array([wt for _, wt in factors])
    avail = norm.notna().to_numpy()
    X = norm.fillna(0).to_numpy()
    coverage = avail @ w
    with np.errstate(invalid="ignore", divide="ignore"):
        contrib = X * w / coverage[:, None]
    ranked_mask = coverage >= MIN_COVERAGE - 1e-9

    # Monte Carlo rank stability (deterministic with a fixed seed)
    rng = np.random.default_rng(seed)
    draws = rng.dirichlet(w * DIRICHLET_CONCENTRATION, size=n_draws)  # (D, F)
    idx = np.flatnonzero(ranked_mask)
    rank_lo = rank_hi = np.zeros(n, dtype=int)
    if len(idx):
        Xr, Ar = X[idx], avail[idx]
        s = (Xr @ draws.T) / (Ar @ draws.T)  # (E, D)
        order = (-s).argsort(axis=0).argsort(axis=0) + 1  # rank per draw
        rank_lo = np.zeros(n, dtype=int)
        rank_hi = np.zeros(n, dtype=int)
        rank_lo[idx] = np.percentile(order, 10, axis=1, method="nearest").astype(int)
        rank_hi[idx] = np.percentile(order, 90, axis=1, method="nearest").astype(int)

    results, excluded = [], []
    any_synth = False
    for i, e in ents.iterrows():
        breakdown = []
        for j, (f, wt) in enumerate(factors):
            has = bool(avail[i, j])
            is_syn = bool(synth.iloc[i, j])
            any_synth |= is_syn and has
            breakdown.append(
                {
                    "feature": f.feature,
                    "label": f.label,
                    "direction": f.direction,
                    "raw": None if not has else float(raw.iloc[i, j]),
                    "year": years[f.feature],
                    "normalized": None if not has else round(float(X[i, j]), 1),
                    "weight": round(float(wt), 4),
                    "contribution": round(float(contrib[i, j]), 2) if has and ranked_mask[i] else 0.0,
                    "is_synthetic": is_syn,
                    "sources": data.sources.get(f.feature, []),
                }
            )
        entity = {
            "level": e["level"],
            "soato": e["soato"],
            "name": e["name"],
            "region_soato": e.get("region_soato"),
            "kind": e.get("kind"),
        }
        if not ranked_mask[i]:
            missing = [b["feature"] for b in breakdown if b["raw"] is None]
            excluded.append({"entity": entity, "coverage": round(float(coverage[i]), 3), "missing_features": missing})
            continue
        warnings = []
        if coverage[i] < 1:
            missing = [b["label"] for b in breakdown if b["raw"] is None]
            warnings.append(f"Partial data: {', '.join(missing)} not available; weights renormalised.")
        if bool(e.get("geom_approx", False)):
            warnings.append("Approximate location on the map (no official boundary polygon).")
        if budget_uzs is not None and budget_uzs < profile.min_budget_uzs:
            warnings.append(
                f"Budget below the typical minimum for {profile.display_name.en.lower()} "
                f"({profile.min_budget_uzs:,} UZS)."
            )
        results.append(
            {
                "entity": entity,
                "score": round(sum(b["contribution"] for b in breakdown), 2),
                "rank_range": [int(rank_lo[i]), int(rank_hi[i])],
                "coverage": round(float(coverage[i]), 3),
                "breakdown": breakdown,
                "warnings": warnings,
            }
        )

    results.sort(key=lambda r: -r["score"])
    for rank, r in enumerate(results, 1):
        r["rank"] = rank
    return {
        "business_type": profile.business_type,
        "display_name": profile.display_name.model_dump(),
        "data_mode": "demo" if any_synth else "official",
        "disclaimer": DISCLAIMER,
        "normalization": profile.normalization,
        "target": target,
        "weights": {f.feature: round(wt, 4) for f, wt in factors},
        "years_used": years,
        "budget_warning": budget_uzs is not None and budget_uzs < profile.min_budget_uzs,
        "min_budget_uzs": profile.min_budget_uzs,
        "results": [{"rank": r.pop("rank"), **r} for r in results],
        "excluded_insufficient_data": excluded,
    }
