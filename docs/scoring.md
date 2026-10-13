# Business Opportunity Score — method

The Business Opportunity Score (BOS) ranks territories for a business type. **It is an analytical model
built from official statistics — decision support, not a guarantee.** Every result shows its full factor
breakdown, so a user can see why a district ranks where it does and disagree with the weights.

Code: `ml/scoring/engine.py` (pure Python, no LLM) · profiles: `ml/profiles/*.yaml` · service:
`backend/app/services/recommendations.py` · API: `POST /api/v1/recommend` · MCP: `calculate_business_score`.

## How the Business Opportunity Score is calculated

1. **Scope.** All 208 districts and cities, or the districts of one region (`region` parameter), or the
   14 regions (`level: region`).
2. **Features.** Each profile lists factors — features from `ml/features/definitions.yaml` such as
   `population`, `food_services_per_capita` or `business_density`. For every factor the engine uses the
   **latest year in which at least half of the territories have a value**, and reports that year.
3. **Normalisation (0–100 within the scope).** Default `percentile`: the lowest territory gets 0, the
   highest 100, ties share the average rank. `minmax_winsorized` clips at the 5th/95th percentile first.
   Factors with direction `-` (e.g. *Low competition* = low business density) are inverted: `100 − x`.
4. **Weighted sum.** `score = Σ wᵢ · xᵢ`. The contribution of a factor is `wᵢ · xᵢ`; contributions always
   add up exactly to the score (they are rounded once and the score is their sum).
5. **Coverage.** Coverage = share of the weights whose factor has data. If coverage < 0.7 the territory
   is **excluded and listed as "insufficient data"**, not ranked. Between 0.7 and 1 the available weights
   are renormalised to 1 and the result carries a "Partial data" warning.
6. **Stability.** 200 Monte Carlo draws perturb the weights (Dirichlet, ≈ ±20 %) with a fixed seed. Each
   result shows the p10–p90 **rank range**: `1–1` means the rank does not depend on the exact weights;
   `3–7` means it does.
7. **Budget.** Each profile has `min_budget_uzs`. A lower budget produces a warning, never a filter.
8. **Goals.** `target = high_growth | stable_demand | low_competition` multiplies weights by tag
   (`ml/profiles/_targets.yaml`) and renormalises — configuration, not code.
9. **Persistence.** Each request is stored in `recommendations` with its `request_id` for monitoring.

## Profiles

11 profiles: supermarket, restaurant, cafe, bakery, pharmacy, private clinic, education center,
logistics, retail store, manufacturing, agri-business. Pharmacy and clinic use health services and
`clinics_per_10k` with direction `-` (an underserved area scores higher); education center uses education
services; logistics uses transport services and a *high* business density (more business clients).

**A new business type is a new YAML file** — Pydantic validates that weights sum to 1 and that every
feature exists. Example:

```yaml
business_type: bakery
display_name: {en: Bakery, uz: Novvoyxona, ru: Пекарня}
min_budget_uzs: 150_000_000
factors:
  - {feature: population,               weight: 0.25, direction: "+", label: Large population}
  - {feature: food_services_per_capita, weight: 0.15, direction: "+", label: Food-service spending}
  - {feature: business_density,         weight: 0.10, direction: "-", label: Low competition}
```

## Limitations

- Percentile normalisation is **relative**: a score of 80 means "better than most territories in this
  scope", not an absolute level of demand. Scores from different scopes are not comparable.
- Weights are expert assumptions. The rank range and the `weights_override` parameter make their
  influence visible; the ablation in `docs/evaluation_report.md` shows each factor's effect.
- Inputs are annual and partly lagged (services 2020–2025, population to 2026). There is no official
  district-level income, rent, footfall or competitor-location data, so the score cannot capture them.
- Accommodation & food services volume is concentrated in regional centres; very high per-capita values
  in cities partly reflect tourism and business travel, not only local demand.
- Forecast-based factors (`forecast_population_growth`) are model predictions and are disabled by default.
