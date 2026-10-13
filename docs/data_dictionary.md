# Data dictionary

## Indicators (official, from SIAT)

Internal codes are defined in `data/reference/indicator_map.yaml` (a new indicator = a new entry there +
`python manage.py ingest`). Units are normalised once, in the loader: people (not thousands), UZS (not
billions). Growth datasets ("% of previous year", 100 = no change) are stored as published and never summed.

| Code | SIAT id | Stored unit | Levels | Years | Additive |
|---|---|---|---|---|---|
| `population_total` | 246 | persons | country, region, district | 2010–2026 | yes |
| `population_urban` | 248 | persons | country, region, district | 2010–2026 | yes |
| `population_rural` | 247 | persons | country, region, district | 2010–2026 | yes |
| `population_{urban,rural}_{women,men}` | 4116–4119 | persons | country, region | 2008–2026 | yes |
| `enterprises_active` | 2044 | units | all | 2017–2026 | yes |
| `enterprises_registered` | 2046 | units | all | 2017–2026 | yes |
| `enterprises_new` | 2049 | units | all | 2016–2025 | yes |
| `market_services_volume` | 4482 | UZS | all | 2020–2025 | yes |
| `market_services_growth` | 4483 | % of previous year | all | 2020–2025 | no |
| `market_services_per_capita` | 3414 | UZS | all | 2020–2025 | no |
| `trade_services_volume` / `_growth` | 4464 / 4465 | UZS / % | all | 2020–2025 | yes / no |
| `food_services_volume` / `_growth` (accommodation & food) | 4462 / 4463 | UZS / % | all | 2020–2025 | yes / no |
| `health_services_volume` / `_growth` | 4470 / 4471 | UZS / % | all | 2020–2025 | yes / no |
| `education_services_volume` / `_growth` | 4468 / 4469 | UZS / % | all | 2020–2025 | yes / no |
| `transport_services_volume` / `_growth` | 4460 / 4461 | UZS / % | all | 2020–2025 | yes / no |
| `hospitals` | 1418 | units | all | 2010–2025 | yes |
| `outpatient_clinics` | 1362 | units | all | 2010–2025 | yes |
| `small_business_share_gva` | 1840 | % of GVA | country, region | 2015–2025 | no |
| *(reference)* district kind | 307 | 1 = district, 0 = city | district | — | — |

## Tables

| Table | Contents | Written by |
|---|---|---|
| `data_sources` | source name, URL, licence, retrieval time | `pipelines/load_siat.py` |
| `regions`, `districts` | SOATO code, names (en/uz/ru), kind, centroid, `geom_approx`, PostGIS `geom` | `load_siat.py`, `load_reference.py` |
| `indicators` | internal code, unit, multiplier, additivity, SIAT dataset id | `load_siat.py` |
| `observations` | one value per indicator × territory × period with `source_url`, `retrieved_at`, `raw_sha256`, `is_synthetic` | `load_siat.py` |
| `ingestion_runs` | loader runs: rows in / loaded / rejected | `load_siat.py` |
| `features` | feature × territory × year: value, `quality_flag`, `lineage` (observation ids), `is_synthetic`, `feature_version` | `ml/features/pipeline.py`, `ml/forecasting/train.py` |
| `recommendations` | each scoring request: parameters, top-10, full result JSON | `app/services/recommendations.py` |
| `predictions` | forecasts: model, origin year, horizon, yhat, 80/95 % bounds, `low_confidence` | `ml/forecasting/train.py` |
| `model_metrics` | backtest and evaluation metrics (`kind` forecast / reco / agent / rag, `split` backtest / eval) | train, evaluation |
| `agent_runs`, `agent_tool_calls` | every chat run: language, mode, latency, tokens, cost, verification failures; each tool call | `app/services/chat.py` |
| `feedback` | 👍 / 👎 with optional comment | `app/services/feedback.py` |
| `rag_chunks` | documentation chunks, full-text vector `tsv`, optional embedding | `rag/ingest.py` |
| `monitor_metrics` | batch metric snapshots exported as Prometheus gauges | `monitoring/drift.py` |

## Traceability

Every statistical API response and tool result carries `meta {sources[{name, url, siat_dataset_id}], period,
unit, is_synthetic, retrieved_at}`; every score factor lists the SIAT datasets it is computed from; every
feature row stores the observation ids it used.
