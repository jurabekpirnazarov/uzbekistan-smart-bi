# Known limitations of the data and the models

Read this before using any number from the platform for a real decision.

## Data

- **Annual frequency.** Every indicator used is yearly. Seasonality and recent months are invisible.
- **Short services series.** District services volumes and growth start in **2020** (6 points). Forecasts
  for them are flagged *low confidence* and only simple models are allowed.
- **No district-level income or wages.** There is no official income, wage, rent or prices data by
  district in the warehouse. The agent answers "I don't have sufficient official data to answer this
  reliably." for such questions.
- **No age structure by district.** The 0–14 share would help education / pharmacy profiles; it is not
  published at district level in the datasets loaded so far.
- **Retail turnover by district is not published**; trade services volume is used as the closest proxy.
- **Regional GRP** is quarterly and needs a cumulative-vs-discrete check before it can be used
  (`region_grp_per_capita` is defined but has no input yet).
- **Methodology breaks.** The 2026 business counts jump sharply (feature drift alert PSI ≈ 7.8 for
  `business_growth`); treat 2025→2026 business growth with caution until SIAT confirms the series.
- **Accommodation & food services** are combined in one SIAT dataset; per-capita values are very high in
  regional centres (tourism, business travel).

## Geography

- Boundaries come from 2020 sources (geoBoundaries / OCHA, dirixtt). **9 districts created after 2020**
  (e.g. Kukdala, Yangikhayot, Davlatabad) have no polygon; they are drawn as **approximate points** inside
  the district they were formed from and flagged `geom_approx = true` everywhere.
- Region polygons are simplified (tolerance 0.005°); a few district centroids fall just outside their
  coarse region outline. This does not affect any statistic.

## Models

- **Business Opportunity Score = decision support, not a guarantee.** Weights are assumptions; the rank
  range shows how much the ranking depends on them. Percentile scores are relative to the scope.
- **Forecasts are model predictions**, never official statistics. Intervals come from backtest errors of
  only three yearly origins, so they can be too narrow in unusual years.
- **Gold labels** for the recommendation evaluation must be expert judgement. The current file contains
  placeholder labels; the evaluation numbers prove the pipeline works, not that the recommendations are good.

## AI analyst

- The LLM explains tool results; it never computes numbers. A verifier checks every number in the answer
  against tool results and shows "✓ N numbers verified" or "⚠ unverified: …". Rounded or rescaled numbers
  are accepted within 2 %; a number written in an unusual form can be flagged although it is correct.
- Without `OPENAI_API_KEY` a rule-based planner answers. It understands common phrasings in English,
  Uzbek and Russian but not complex multi-step questions.
- No synthetic data is loaded (`DATA_MODE=official`). If synthetic gap-fill is ever added, every such value
  is labelled "DEMO / SYNTHETIC DATA — not official statistics".
