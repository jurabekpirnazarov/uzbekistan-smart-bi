"""Generate docs/features.md from definitions.yaml + the feature-type docstrings (PLAN.md Phase 3).

Usage:  python -m ml.features.docs
"""

from __future__ import annotations

import inspect
from pathlib import Path

from ml.features.pipeline import load_definitions
from ml.features.registry import FEATURE_TYPES

ROOT = Path(__file__).resolve().parents[2]

MEANING = {
    "population": "Market size: how many people live in the territory.",
    "population_growth": "Year-on-year population growth — a growing market.",
    "population_cagr_5y": "Long-run (5-year) compound population growth.",
    "urbanization": "Share of the population living in urban settlements.",
    "business_density": "Operating businesses per 1,000 people — a proxy for competition.",
    "new_business_rate": "New businesses relative to operating ones — business dynamism.",
    "business_growth": "Year-on-year growth of operating businesses.",
    "services_per_capita": "Market services per person (UZS) — purchasing activity.",
    "trade_per_capita": "Trade services per person (UZS) — retail demand proxy.",
    "food_services_per_capita": "Accommodation & food services per person (UZS).",
    "health_services_per_capita": "Health services per person (UZS).",
    "education_services_per_capita": "Education services per person (UZS).",
    "transport_services_per_capita": "Transport services per person (UZS).",
    "trade_growth": "Real growth of trade services (official index → rate).",
    "food_services_growth": "Real growth of accommodation & food services.",
    "health_services_growth": "Real growth of health services.",
    "education_services_growth": "Real growth of education services.",
    "transport_services_growth": "Real growth of transport services.",
    "clinics_per_10k": "Outpatient clinics per 10,000 people — health supply.",
    "hospitals_per_10k": "Hospitals per 10,000 people — health supply.",
    "region_grp_per_capita": "Regional GRP per person (region context; input not yet in the warehouse).",
    "region_small_business_share": "Small-business share of the region's GVA (region context).",
    "is_city": "1 for cities, 0 for districts (tuman).",
}


def formula(spec: dict) -> str:
    t = spec["type"]
    if t == "passthrough":
        return f"`{spec['indicator']}`"
    if t == "growth":
        return f"`{spec['indicator']}_t / {spec['indicator']}_(t-{spec.get('lag', 1)}) − 1`"
    if t == "cagr":
        n = spec["years"]
        return f"`({spec['indicator']}_t / {spec['indicator']}_(t-{n}))^(1/{n}) − 1`"
    if t == "ratio":
        return f"`{spec['num']} / {spec['den']}`"
    if t == "per_capita":
        per = spec.get("per", 1)
        return f"`{spec['num']} / {spec.get('den', 'population_total')}" + (f" × {per:,}`" if per != 1 else "`")
    if t == "index_to_rate":
        return f"`{spec['indicator']} / 100 − 1` (112.3 → 0.123)"
    if t == "region_context":
        inner = f"{spec['num']} / {spec['den']}" if "num" in spec else spec["indicator"]
        return f"`{inner}` of the parent region"
    if t == "reference":
        return f"`{spec['field']} == '{spec['equals']}'`"
    return t


def main() -> None:
    defs = load_definitions()
    lines = [
        "# Features",
        "",
        "_Generated from `ml/features/definitions.yaml` by `python -m ml.features.docs`._",
        "",
        "Features are computed by `python manage.py features` into the `features` table for every country /",
        "region / district and year where the inputs exist. Rules: missing inputs → NULL with a `quality_flag`",
        "(never imputed); any synthetic input → `is_synthetic = true`; `lineage` lists the observation ids used;",
        "region-context features are broadcast to the districts of the region and are never presented as",
        "district facts. A new feature is a new line in the YAML — no code change.",
        "",
        "| Feature | Type | Formula | Business meaning |",
        "|---|---|---|---|",
    ]
    for name, spec in defs.items():
        lines.append(f"| `{name}` | {spec['type']} | {formula(spec)} | {MEANING.get(name, '')} |")
    lines += ["", "## Feature types", ""]
    for t, fn in FEATURE_TYPES.items():
        doc = inspect.getdoc(fn) or ""
        lines.append(f"- **{t}** — {doc.splitlines()[0] if doc else ''}")
    lines += [
        "",
        "## Forecast features (model predictions)",
        "",
        "`forecast_population_growth` and `forecast_business_growth` are written by `python manage.py train`:",
        "the annualised growth from the last official value to the 2-year forecast. They carry",
        "`quality_flag = 'model_prediction'` and are only used by profiles that enable them as optional factors.",
        "",
    ]
    (ROOT / "docs" / "features.md").write_text("\n".join(lines), encoding="utf-8")
    print("docs/features.md written")


if __name__ == "__main__":
    main()
