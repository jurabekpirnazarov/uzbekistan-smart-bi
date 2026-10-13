# Features

_Generated from `ml/features/definitions.yaml` by `python -m ml.features.docs`._

Features are computed by `python manage.py features` into the `features` table for every country /
region / district and year where the inputs exist. Rules: missing inputs → NULL with a `quality_flag`
(never imputed); any synthetic input → `is_synthetic = true`; `lineage` lists the observation ids used;
region-context features are broadcast to the districts of the region and are never presented as
district facts. A new feature is a new line in the YAML — no code change.

| Feature | Type | Formula | Business meaning |
|---|---|---|---|
| `population` | passthrough | `population_total` | Market size: how many people live in the territory. |
| `population_growth` | growth | `population_total_t / population_total_(t-1) − 1` | Year-on-year population growth — a growing market. |
| `population_cagr_5y` | cagr | `(population_total_t / population_total_(t-5))^(1/5) − 1` | Long-run (5-year) compound population growth. |
| `urbanization` | ratio | `population_urban / population_total` | Share of the population living in urban settlements. |
| `business_density` | per_capita | `enterprises_active / population_total × 1,000` | Operating businesses per 1,000 people — a proxy for competition. |
| `new_business_rate` | ratio | `enterprises_new / enterprises_active` | New businesses relative to operating ones — business dynamism. |
| `business_growth` | growth | `enterprises_active_t / enterprises_active_(t-1) − 1` | Year-on-year growth of operating businesses. |
| `services_per_capita` | passthrough | `market_services_per_capita` | Market services per person (UZS) — purchasing activity. |
| `trade_per_capita` | per_capita | `trade_services_volume / population_total` | Trade services per person (UZS) — retail demand proxy. |
| `food_services_per_capita` | per_capita | `food_services_volume / population_total` | Accommodation & food services per person (UZS). |
| `health_services_per_capita` | per_capita | `health_services_volume / population_total` | Health services per person (UZS). |
| `education_services_per_capita` | per_capita | `education_services_volume / population_total` | Education services per person (UZS). |
| `transport_services_per_capita` | per_capita | `transport_services_volume / population_total` | Transport services per person (UZS). |
| `trade_growth` | index_to_rate | `trade_services_growth / 100 − 1` (112.3 → 0.123) | Real growth of trade services (official index → rate). |
| `food_services_growth` | index_to_rate | `food_services_growth / 100 − 1` (112.3 → 0.123) | Real growth of accommodation & food services. |
| `health_services_growth` | index_to_rate | `health_services_growth / 100 − 1` (112.3 → 0.123) | Real growth of health services. |
| `education_services_growth` | index_to_rate | `education_services_growth / 100 − 1` (112.3 → 0.123) | Real growth of education services. |
| `transport_services_growth` | index_to_rate | `transport_services_growth / 100 − 1` (112.3 → 0.123) | Real growth of transport services. |
| `clinics_per_10k` | per_capita | `outpatient_clinics / population_total × 10,000` | Outpatient clinics per 10,000 people — health supply. |
| `hospitals_per_10k` | per_capita | `hospitals / population_total × 10,000` | Hospitals per 10,000 people — health supply. |
| `region_grp_per_capita` | region_context | `grp_annual / population_total` of the parent region | Regional GRP per person (region context; input not yet in the warehouse). |
| `region_small_business_share` | region_context | `small_business_share_gva` of the parent region | Small-business share of the region's GVA (region context). |
| `is_city` | reference | `districts.kind == 'city'` | 1 for cities, 0 for districts (tuman). |

## Feature types

- **passthrough** — 
- **growth** — v_t / v_{t-lag} - 1
- **cagr** — (v_t / v_{t-years})^(1/years) - 1, only for positive values.
- **ratio** — 
- **per_capita** — num / population * per (per=1 → per person, 1000 → per 1,000 people).
- **index_to_rate** — '% of previous year' index → growth rate: 112.3 → 0.123.
- **region_context** — Region-level value broadcast to all districts of the region (never presented as a district fact).
- **reference** — Attribute of the territory itself, e.g. districts.kind == city → 1.0 / 0.0 (districts only).

## Forecast features (model predictions)

`forecast_population_growth` and `forecast_business_growth` are written by `python manage.py train`:
the annualised growth from the last official value to the 2-year forecast. They carry
`quality_flag = 'model_prediction'` and are only used by profiles that enable them as optional factors.
