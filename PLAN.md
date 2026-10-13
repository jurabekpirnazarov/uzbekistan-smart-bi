# PLAN.md — Build Plan: from SIAT data to a running app

Step-by-step plan for building **Uzbekistan Smart Business Intelligence** with Claude Code.
Covers everything: data download → warehouse → features → recommendations → forecasts →
API → MCP → RAG + agent → frontend + 3D map → Docker → monitoring → evaluation → docs.

## How to use this file

1. Put `CLAUDE.md`, `PLAN.md` and `pipelines/siat_ingest.py` in the project root (`ITPU/`).
2. Open PowerShell in that folder and run `claude`.
3. For each phase, copy the **Prompt** block into Claude Code. Press `Shift+Tab` for plan mode first,
   review the plan, then approve.
4. When it finishes, run the **Verify** commands yourself.
5. `git commit` after every phase. Then `/clear` and start the next phase.

Never combine phases in one session. Large phases (7, 8, 9) can be split into "backend" and "integration".

## Phase overview

| # | Phase | Internship week | Main deliverable |
|---|---|---|---|
| 0 | Repository, Docker, task runner | 1 | `docker compose up` brings up an empty working stack |
| 1 | Data warehouse (SIAT → Postgres) | 1–2 | Schema, indicator map, loader, validation |
| 2 | Geography & reference data | 2 | Regions/districts with geometry + SOATO |
| 3 | Feature engineering | 3 | Reusable YAML feature pipeline |
| 4 | Recommendation engine | 4 | Business Opportunity Score + 11 business profiles |
| 5 | Forecasting + MLflow | 4 | Backtested baseline models with uncertainty |
| 6 | FastAPI API | 6 | REST + SSE endpoints with source metadata |
| 7 | MCP server | 2, 5 | Statistical tools exposed over MCP |
| 8 | RAG + Agentic AI | 5 | Tool-using agent with numeric verification |
| 9 | Frontend: dashboard, 3D map, chat | 8 | Product-quality UI |
| 10 | Monitoring | 7 | Prometheus metrics, drift, 5 Grafana dashboards, alerts |
| 11 | Evaluation | 7 | P@K, R@K, NDCG@K, MAE/RMSE/MAPE, agent metrics |
| 12 | Hardening & one-command launch | 8 | `python manage.py demo` + clean-machine test |
| 13 | Documentation & presentation | 8 | Architecture, report, demo script |

---

## Phase 0 — Repository, Docker, task runner

### Goal
A clean repository where `docker compose up -d --build` starts every service with healthchecks,
even before there is real logic.

### Docker Compose services

| Service | Image / build | Port | Purpose |
|---|---|---|---|
| `db` | `db/Dockerfile`: `postgis/postgis:16-3.4` + `postgresql-16-pgvector` | 5432 | Warehouse, PostGIS, pgvector |
| `backend` | `backend/Dockerfile` (python:3.11-slim) | 8000 | FastAPI, `/metrics` |
| `mcp` | `mcp_server/Dockerfile` | 8100 | MCP server (streamable-http) |
| `worker` | same image as backend, different command | — | ingest / features / train / eval jobs |
| `frontend` | `frontend/Dockerfile` (node build → nginx) | 5173 | UI, proxies `/api` to backend |
| `prometheus` | `prom/prometheus` | 9090 | Metrics + alert rules |
| `grafana` | `grafana/grafana` | 3000 | Provisioned dashboards |
| `mlflow` | `ghcr.io/mlflow/mlflow` (backend store = Postgres, artifacts = volume) | 5000 | Experiments, model registry |
| `postgres-exporter` | `prometheuscommunity/postgres-exporter` | 9187 | DB metrics |

Optional: `docker-compose.observability.yml` adds Langfuse (or Jaeger) for tracing.

### Prompt
```
Read CLAUDE.md and PLAN.md. Implement Phase 0 only.

1. Create the repository layout from CLAUDE.md. Keep pipelines/siat_ingest.py and data/ as they are.
2. db/Dockerfile: FROM postgis/postgis:16-3.4, install postgresql-16-pgvector;
   db/init/01_extensions.sql: CREATE EXTENSION postgis; CREATE EXTENSION vector;
   create a separate "mlflow" database.
3. backend: FastAPI app factory, pydantic-settings config, SQLAlchemy 2.0 engine, Alembic setup,
   structlog JSON logging with request_id middleware, GET /health (pings DB),
   GET /metrics (prometheus-fastapi-instrumentator). Package it as installable (pyproject.toml)
   so mcp_server and worker can import app.services.
4. mcp_server: placeholder FastMCP server with one "ping" tool, streamable-http on 8100.
5. frontend: React + Vite + TypeScript, one page that calls /api/v1/health. nginx config proxies /api.
6. docker-compose.yml with all services from PLAN.md Phase 0, healthchecks, depends_on: condition
   service_healthy, named volumes (pgdata, grafana_data, mlflow_artifacts), ./data mounted into
   backend and worker.
7. monitoring/prometheus/prometheus.yml scraping backend, mcp, postgres-exporter.
   monitoring/grafana/provisioning: Prometheus + Postgres datasources.
8. .env.example: OPENAI_API_KEY=, OPENAI_MODEL=gpt-4.1-mini, OPENAI_EMBED_MODEL=text-embedding-3-small,
   DATABASE_URL, VECTOR_DB_URL (same Postgres), MAPBOX_TOKEN= (optional), DATA_MODE=official,
   MLFLOW_TRACKING_URI=http://mlflow:5000, OTEL_ENABLED=false.
9. manage.py (Typer): up, down, logs, ingest, seed, features, train, eval, monitor, test, lint, demo.
   Commands that need the DB run inside the worker container via `docker compose run --rm worker ...`.
10. .gitignore, .gitattributes (eol=lf), .github/workflows/ci.yml (ruff + pytest with a postgis service).
11. README.md quick start for Windows PowerShell.
Stop and summarise.
```

### Verify
```powershell
copy .env.example .env
docker compose up -d --build
docker compose ps                      # all services healthy
curl http://localhost:8000/health      # {"status":"ok","db":"ok"}
start http://localhost:5173            # frontend shows API status
start http://localhost:3000            # Grafana (admin/admin)
start http://localhost:5000            # MLflow
```

---

## Phase 1 — Data warehouse (SIAT → PostgreSQL)

### Goal
Official SIAT data loaded into a normalised, traceable schema. Raw dataset ids never leak
past the loader; everything downstream uses internal indicator codes.

### Schema (Alembic)
```
data_sources(id, name, url, kind[siat|synthetic|manual|geo], license, retrieved_at)
regions(id, soato_code, name_en, name_uz, name_ru, geom MultiPolygon 4326, centroid Point 4326)
districts(id, soato_code, region_id, name_en, name_uz, name_ru, kind[district|city],
          geom MultiPolygon NULL, centroid Point, geom_approx bool)
indicators(id, code, name_en, name_uz, category, unit, unit_multiplier, level_available[],
           frequency, additive bool, higher_is_better bool, siat_dataset_id, description, methodology_ref)
observations(id, indicator_id, level[country|region|district], region_id, district_id,
             year, quarter, month, period_label, value numeric, unit,
             source_id, source_url, retrieved_at, raw_sha256, is_synthetic bool, quality_flag, ingested_at)
             UNIQUE(indicator_id, level, region_id, district_id, year, quarter, month, source_id)
features(id, level, region_id, district_id, year, feature_name, value, is_synthetic, lineage jsonb,
         feature_version, computed_at)
predictions(id, indicator_id, level, region_id, district_id, target_year, yhat, yhat_lower_80,
            yhat_upper_80, yhat_lower_95, yhat_upper_95, model_name, model_version, horizon,
            trained_until, history_points, created_at)
recommendations(id, request_id, business_type, scope jsonb, rank, level, entity_id, score,
                breakdown jsonb, weights jsonb, rank_p10, rank_p90, coverage, data_mode, created_at)
model_metrics(id, model_name, model_version, indicator_code, metric, value, split, horizon, created_at)
ingestion_runs(id, source_id, started_at, finished_at, status, datasets_ok, datasets_failed,
               rows_in, rows_loaded, rows_rejected, error)
data_quality_checks(id, run_id, check_name, indicator_code, passed bool, details jsonb, created_at)
agent_runs(id, request_id, session_id, user_query, lang, intent, plan jsonb, final_answer,
           latency_ms, prompt_tokens, completion_tokens, cost_usd, status, error, created_at)
agent_tool_calls(id, agent_run_id, tool_name, args jsonb, result_summary, ok bool, latency_ms, created_at)
user_feedback(id, request_id, rating smallint, comment, created_at)
rag_chunks(id, doc_id, title, source_url, chunk_index, content, embedding vector(1536), tsv tsvector, metadata jsonb)
```
SQL views for convenience: `v_latest_observation`, `v_district_panel` (wide: one row per district-year).

### Indicator map (`data/reference/indicator_map.yaml`)
See **Appendix A** for the full list. Each entry:
```yaml
population_total:
  siat_dataset_id: 246
  name_en: Permanent population, total
  category: population
  level: [country, region, district]
  unit: persons
  source_unit: thousand people
  unit_multiplier: 1000
  frequency: annual
  additive: true
  higher_is_better: true
```

### Prompt
```
Read CLAUDE.md and PLAN.md. Implement Phase 1.

1. Alembic migration with the full schema from PLAN.md Phase 1 (PostGIS geometry, pgvector, tsvector,
   indexes on (indicator_id, level, year), (district_id), (region_id)).
2. data/reference/indicator_map.yaml with every entry from PLAN.md Appendix A.
   Validate it with a Pydantic model on load.
3. pipelines/load_siat.py:
   - reads data/processed/observations.csv + indicators.csv produced by pipelines/siat_ingest.py
   - keeps only datasets present in indicator_map.yaml
   - applies unit_multiplier, maps to internal codes, links region/district by SOATO
   - builds the districts table from SIAT dataset 307 (value 1 = district, 0 = city; it is a
     reference, not an indicator) plus regions from data/processed/regions.csv
   - upserts (idempotent: running twice changes nothing)
   - writes ingestion_runs
4. Quarterly region datasets (1582, 1588, 1589): detect whether values are cumulative
   (Jan–Mar, Jan–Jun, ...) or discrete quarters by comparing Q4 with the annual total where
   available; store an annual series accordingly (indicator suffix _annual). Document the finding.
5. pipelines/validate.py writing to data_quality_checks:
   - district sum vs region total within ±2% for additive indicators
   - region sum vs country total within ±2%
   - no negative counts, percentages 0–1000 for growth indices
   - year coverage per indicator, missing ratio per indicator × region
   - known source issue: dataset 1871 contains period '2025-Q5' (skipped by parser)
6. pipelines/generate_synthetic.py: ONLY for indicators listed under `synthetic_fill` in
   indicator_map.yaml (avg_monthly_wage at district level). Deterministic seed, plausible values
   derived from region totals, is_synthetic=true, source=synthetic_v1.
7. manage.py ingest = siat_ingest.py fetch --ids <ids from indicator_map.yaml> && load_siat.py && validate.py
8. docs/data_dictionary.md generated from indicator_map.yaml (code, name, unit, level, years, source, notes).
9. Tests: unit conversion, idempotent upsert, sum checks, growth-rate datasets never summed,
   districts from 307 have the right kind.
Stop and summarise, including row counts per indicator and the cumulative-vs-discrete finding.
```

### Verify
```powershell
python manage.py ingest
docker compose exec db psql -U postgres -d sbi -c "select i.code, o.level, count(*), min(o.year), max(o.year) from observations o join indicators i on i.id=o.indicator_id group by 1,2 order by 1,2;"
docker compose exec db psql -U postgres -d sbi -c "select check_name, passed, count(*) from data_quality_checks group by 1,2;"
python manage.py test
```

---

## Phase 2 — Geography & reference data

### Goal
Every region and district has a geometry or a centroid so it can be drawn on the 3D map.

### Facts already checked
- `github.com/dirixtt/GeoJSON-Uzbekistan` (MIT): `uzbekistan_regional.geojson` has 14 regions with
  `ADM1_EN/UZ/RU` names — good quality.
- Its district files are inconsistent: name keys vary, Bukhara/Navoi/Khorezm have no names,
  Namangan is missing.
- geoBoundaries UZB ADM2 (CC BY 4.0) is a better district source, but it is stored in Git LFS
  (`media.githubusercontent.com`) — download manually if the container cannot reach it.

### Approach
- Regions: polygons (3D extrusion on the map).
- Districts: polygons where a reliable name match exists, otherwise centroids (3D columns).
  Approximate centroids are flagged `geom_approx=true` and rendered differently in the UI.
- Name matching: normalise transliterations (o'/oʻ/o', g'/gʻ, x/kh, q/k, "tumani"/"district"/"city"),
  fuzzy match with `rapidfuzz` ≥ 90, log every unmatched district to `data/reference/unmatched_districts.csv`.

### Prompt
```
Read CLAUDE.md and PLAN.md. Implement Phase 2.

1. pipelines/load_reference.py:
   - download the region GeoJSON from https://codeload.github.com/dirixtt/GeoJSON-Uzbekistan/zip/refs/heads/main
     into data/reference/geo/ (cache it; never re-download if present)
   - if data/reference/geo/geoBoundaries-UZB-ADM2.geojson exists, use it for districts
   - simplify geometries (shapely, tolerance 0.005), map regions to SOATO via names, store geom + centroid
   - match districts by normalised name (rapidfuzz ≥ 90) within the same region; store polygons;
     unmatched → data/reference/district_centroids.csv (manual lat/lon) with geom_approx=true
   - write unmatched names to data/reference/unmatched_districts.csv
2. data/reference/LICENSES.md for all geo sources.
3. Export pre-built GeoJSON for the frontend: data/processed/geo/regions.geojson,
   data/processed/geo/districts.geojson (properties: soato_code, names, kind, geom_approx).
4. Hook into `python manage.py seed`.
5. Tests: 14 regions with geometry; every district has a centroid; no district centroid falls
   outside its region polygon (warn, not fail, for approx ones).
Stop and summarise: how many districts matched to polygons vs centroids.
```

### Verify
```powershell
python manage.py seed
docker compose exec db psql -U postgres -d sbi -c "select geom_approx, count(*), count(geom) from districts group by 1;"
```

---

## Phase 3 — Feature engineering

### Goal
A reusable feature pipeline driven by YAML. No feature is hard-coded for one business type.

### Feature definitions (`ml/features/definitions.yaml`)
```yaml
population:              {type: passthrough, indicator: population_total}
population_growth:       {type: growth, indicator: population_total, lag: 1}
population_cagr_5y:      {type: cagr, indicator: population_total, years: 5}
urbanization:            {type: ratio, num: population_urban, den: population_total}
business_density:        {type: per_capita, num: enterprises_active, per: 1000}
new_business_rate:       {type: ratio, num: enterprises_new, den: enterprises_active}
business_growth:         {type: growth, indicator: enterprises_active, lag: 1}
services_per_capita:     {type: passthrough, indicator: market_services_per_capita}
trade_per_capita:        {type: per_capita, num: trade_services_volume, per: 1}
food_services_per_capita:{type: per_capita, num: food_services_volume, per: 1}
health_services_per_capita: {type: per_capita, num: health_services_volume, per: 1}
education_services_per_capita: {type: per_capita, num: education_services_volume, per: 1}
transport_services_per_capita: {type: per_capita, num: transport_services_volume, per: 1}
trade_growth:            {type: index_to_rate, indicator: trade_services_growth}      # 112.3 → 0.123
food_services_growth:    {type: index_to_rate, indicator: food_services_growth}
health_services_growth:  {type: index_to_rate, indicator: health_services_growth}
education_services_growth: {type: index_to_rate, indicator: education_services_growth}
transport_services_growth: {type: index_to_rate, indicator: transport_services_growth}
clinics_per_10k:         {type: per_capita, num: outpatient_clinics, per: 10000}
hospitals_per_10k:       {type: per_capita, num: hospitals, per: 10000}
region_grp_per_capita:   {type: region_context, num: grp_annual, den: population_total}
region_small_business_share: {type: region_context, indicator: small_business_share_gva}
is_city:                 {type: reference, field: districts.kind, equals: city}
```

### Rules
- Missing inputs → NaN + `quality_flag`, never imputed.
- If a feature uses any synthetic input → feature `is_synthetic=true`.
- `lineage` stores the observation ids used.
- Region-context features are broadcast to all districts of that region.
- "Latest available year" is resolved per feature, and the year actually used is stored.

### Prompt
```
Read CLAUDE.md and PLAN.md. Implement Phase 3.
- ml/features/registry.py: feature types (passthrough, growth, cagr, ratio, per_capita,
  index_to_rate, region_context, reference) as pure functions on pandas DataFrames.
- ml/features/definitions.yaml exactly as in PLAN.md Phase 3.
- ml/features/pipeline.py: compute_features(level, years) → writes the features table
  (feature_version = git short sha or a hash of definitions.yaml), with lineage and is_synthetic.
- backend/app/services/features.py: get_features(level, entities, year, names).
- manage.py features.
- docs/features.md: formula, business meaning and inputs for each feature (generated from YAML + docstrings).
- Tests: each feature type against hand-calculated values; NaN propagation; synthetic flag propagation;
  index_to_rate(112.3) == 0.123.
Stop and summarise with a coverage table: feature × level × years available.
```

---

## Phase 4 — Recommendation engine (Business Opportunity Score)

### Business profiles (`ml/profiles/*.yaml`)
11 profiles: `supermarket, restaurant, cafe, bakery, pharmacy, private_clinic, education_center,
logistics, retail_store, manufacturing, agri_business`.

Example:
```yaml
business_type: bakery
display_name: {en: Bakery, uz: Novvoyxona, ru: Пекарня}
min_budget_uzs: 150_000_000
default_level: district
factors:
  - {feature: population,               weight: 0.25, direction: "+", label: Large population}
  - {feature: population_growth,        weight: 0.15, direction: "+", label: Growing population}
  - {feature: food_services_per_capita, weight: 0.15, direction: "+", label: Food-service spending}
  - {feature: food_services_growth,     weight: 0.15, direction: "+", label: Food-service growth}
  - {feature: business_density,         weight: 0.10, direction: "-", label: Low competition}
  - {feature: urbanization,             weight: 0.10, direction: "+", label: Urban demand}
  - {feature: new_business_rate,        weight: 0.10, direction: "+", label: Business dynamism}
normalization: percentile      # or minmax_winsorized
optional_factors:
  - {feature: forecast_population_growth, weight: 0.10, direction: "+", enabled: false}
```
Pharmacy/clinic use `health_services_*` and `clinics_per_10k` (direction "-"); education center uses
`education_services_*` and the 0–14 age share when available; logistics uses `transport_services_*`.

### Algorithm
1. Resolve scope (country → regions or districts; region → its districts).
2. Load profile features for the latest available year.
3. Normalise each factor 0–100 within scope; invert if `direction: "-"`.
4. `score = Σ wᵢ·xᵢ`; `contributionᵢ = wᵢ·xᵢ` (contributions sum exactly to the score).
5. Coverage = share of weights with data; < 0.7 → entity marked "insufficient data", not ranked.
6. Stability: Monte Carlo (200 draws) perturbing weights ±20% (Dirichlet) → rank p10–p90 per entity.
7. Budget: below `min_budget_uzs` → warning, not a filter.
8. `target` option (`high_growth | stable_demand | low_competition`) re-weights via preset multipliers
   defined in YAML, not code.
9. Persist to `recommendations` with `request_id`.

### Output contract
```json
{
  "request_id": "...",
  "business_type": "bakery",
  "scope": {"level": "district", "region_soato": "1730"},
  "data_mode": "official",
  "disclaimer": "Business Opportunity Score is an analytical model based on available official statistics. It is decision support, not a guarantee.",
  "results": [{
    "rank": 1, "entity": {"level": "district", "soato": "1730...", "name": "Kuva district"},
    "score": 86.4, "rank_range": [1, 3], "coverage": 1.0,
    "breakdown": [{"feature": "population", "label": "Large population", "raw": 245000, "year": 2025,
                   "normalized": 96.0, "weight": 0.25, "contribution": 24.0,
                   "is_synthetic": false, "sources": [{"dataset_id": 246, "url": "..."}]}],
    "warnings": []
  }],
  "excluded_insufficient_data": [...]
}
```

### Prompt
```
Read CLAUDE.md and PLAN.md. Implement Phase 4.
- ml/profiles/: the 11 YAML profiles; Pydantic validation (weights sum to 1.0, features exist in
  definitions.yaml).
- ml/scoring/engine.py: score(business_type, scope, year=None, weights_override=None, target=None)
  implementing every step of the algorithm. Pure Python, no LLM.
- backend/app/services/recommendations.py wraps it and persists results.
- docs/scoring.md: method, normalisation, stability, limitations.
- Tests: contributions sum to score; weights_override works; adding a new YAML profile needs no code;
  low-coverage entities are excluded and reported; stability ranges are deterministic with a fixed seed.
Stop and show the top 5 districts in Fergana region for bakery and pharmacy.
```

---

## Phase 5 — Forecasting + MLflow

### Models
- `naive_last`, `naive_drift` — mandatory baselines
- `linear_trend` — sklearn LinearRegression on year
- `holt` — statsmodels ExponentialSmoothing(trend="add", damped_trend=True)
- `gbm_panel` — XGBoost (or sklearn HistGradientBoosting) on lag features across all districts
- Prophet is not used: annual series with 6–15 points; explain this in the report.

### Targets
`population_total`, `enterprises_active`, `enterprises_new`, `trade_services_volume`,
`food_services_volume`, `health_services_volume`, `market_services_volume` — district and region level.

### Validation
- Rolling-origin backtest; last 3 years are test origins; horizon 1 and 2.
- Metrics: MAE, RMSE, MAPE, sMAPE, plus % improvement over `naive_last`.
- Best model per indicator × level selected by backtest sMAPE.
- Services series start in 2020 (≈6 points): only naive/linear/holt allowed; flag low confidence.

### Uncertainty
80% and 95% intervals from backtest residual quantiles (empirical), widened by √horizon.

### Prompt
```
Read CLAUDE.md and PLAN.md. Implement Phase 5.
- ml/forecasting/base.py interface: fit(history) / predict(horizon) → yhat, intervals.
- ml/forecasting/models.py: the 5 models.
- ml/forecasting/backtest.py: rolling origin, no leakage, metrics → model_metrics + MLflow.
- ml/forecasting/train.py: for each target × level choose the best model, register it in MLflow
  with alias "production", write 1–3 year forecasts to predictions (with history_points and
  a low_confidence flag when history < 8 points).
- Add forecast_population_growth and forecast_<sector>_growth as optional scoring features.
- backend/app/services/forecasts.py.
- manage.py train.
- Tests: no future data in training folds; intervals contain yhat; naive baselines reproduce by hand.
Stop and print the backtest leaderboard per target.
```

### Verify
```powershell
python manage.py train
start http://localhost:5000
```

---

## Phase 6 — FastAPI API

All routes under `/api/v1`. Every statistical response includes
`meta: {sources[], period, unit, is_synthetic, retrieved_at}`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/regions`, `/regions/{soato}/districts` | Reference |
| GET | `/indicators?category=` | Indicator catalogue |
| GET | `/statistics?indicator=&level=&region=&year_from=&year_to=` | Observations with sources |
| GET | `/timeseries/{indicator}/{level}/{soato}` | History + forecast in one series |
| GET | `/compare?indicator=&entities=` | Side-by-side comparison |
| GET | `/overview?year=` | Dashboard KPIs |
| GET | `/geo/regions?metric=&year=` | GeoJSON with metric values |
| GET | `/geo/districts?region=&metric=&year=` | Districts (polygons/centroids) with values |
| GET | `/business-types` | Profiles |
| POST | `/recommend` | `{business_type, region?, budget_uzs?, target?, weights_override?}` |
| GET | `/forecast/{indicator}/{level}/{soato}?horizon=` | Forecast + intervals + model info |
| POST | `/chat` | Agent, SSE (`tool_call`, `token`, `result`, `error`) |
| POST | `/feedback` | 👍/👎 + comment |
| GET | `/monitoring/{data,models,recommendations,agent}` | Monitoring page data |
| GET | `/health`, `/metrics` | Ops |

### Prompt
```
Read CLAUDE.md and PLAN.md. Implement Phase 6.
- Routers only call backend/app/services. Pydantic response models with examples.
- In-process TTL cache (cachetools) for /overview and /geo/*.
- Consistent error model {code, message, details}.
- CORS for the frontend origin; rate limit /chat (slowapi, 20/min per IP).
- Integration tests with httpx.AsyncClient against a seeded test database (pytest fixture).
- docs/api.md generated from OpenAPI.
Stop and summarise.
```

### Verify
```powershell
start http://localhost:8000/docs
curl -X POST http://localhost:8000/api/v1/recommend -H "Content-Type: application/json" -d "{\"business_type\":\"pharmacy\",\"region\":\"1730\"}"
```

---

## Phase 7 — MCP server

### Tools
```
search_statistics(query, category?)
get_indicator(code)
get_region_statistics(region, indicators[], year?)
get_district_statistics(region, district?, indicators[], year?)
get_time_series(indicator, level, entity, year_from?, year_to?)
compare_regions(entities[], indicators[], year?)
get_population_data(level, entity?, year?)
get_income_data(level, entity?, year?)            # returns a clear "no official district data" warning
get_business_activity(level, entity?, year?)
get_retail_data(level, entity?, year?)
forecast_indicator(indicator, level, entity, horizon)
calculate_business_score(business_type, region?, target?, weights_override?)
list_business_types()
retrieve_documents(query, k)
```
Every result: `{data, meta: {sources[], is_synthetic, period}, warnings[]}`; errors are structured.

### Prompt
```
Read CLAUDE.md and PLAN.md. Implement Phase 7.
- mcp_server/ with the official `mcp` Python SDK (FastMCP), stdio + streamable-http on 8100.
- Tools call backend app.services directly (installed package). No duplicated logic.
- Prometheus metrics: mcp_tool_calls_total{tool,status}, mcp_tool_latency_seconds{tool}.
- docs/mcp.md: each tool, arguments, sample output, how to connect with MCP Inspector and Claude Desktop.
- One test per tool.
Stop and summarise.
```

### Verify
```powershell
npx @modelcontextprotocol/inspector     # connect to http://localhost:8100/mcp
```

---

## Phase 8 — RAG + Agentic AI

### RAG
- Sources (`data/docs/`): SIAT dataset metadata (the `metadata_json` field from indicators.csv —
  methodology, definitions), `docs/data_dictionary.md`, `docs/features.md`, `docs/scoring.md`,
  profile YAMLs, and any Stat.uz methodology PDFs placed there manually.
- Chunking: ~800 tokens, 100 overlap, title + source_url in metadata.
- Embeddings: OpenAI `text-embedding-3-small` → pgvector. No key → BM25 only (Postgres tsvector).
- Hybrid retrieval: vector + BM25 with reciprocal rank fusion, top-k 5. Answers always cite sources.

### Agent loop
1. **Intent parse** → `{intent: recommend|compare|forecast|explain|methodology|statistic,
   business_type, location, budget_uzs, horizon, lang}` (structured output).
2. **Plan** → ordered list of tool calls (JSON).
3. **Execute** → max 8 tool calls, per-call timeout, retries on transient errors.
4. **Verify** → every number in the draft answer must appear in a tool result (tolerance for rounding);
   otherwise regenerate once, then strip the number.
5. **Answer** in the user's language (en/uz/ru) with sections:
   Recommendation → Why (breakdown) → Forecast (with interval) → Risks & assumptions → Sources →
   DEMO / SYNTHETIC DATA notice when relevant.
6. Returns `{answer_md, recommendations, map_focus, charts[]}` for the frontend.
7. Logs to `agent_runs` and `agent_tool_calls`.

Fallback without `OPENAI_API_KEY`: keyword intent parser (business names in en/uz/ru, region names),
fixed plans per intent, templated answers.

### Prompt
```
Read CLAUDE.md and PLAN.md. Implement Phase 8.
- rag/ingest.py, rag/retrieve.py (hybrid + RRF), manage.py seed builds the index.
- agents/orchestrator.py (intent → plan → execute → verify → answer), agents/tools.py
  (registry using the MCP client by default, direct services when AGENT_TOOL_MODE=direct),
  agents/prompts/{en,uz,ru}.md, agents/fallback_planner.py, agents/verify.py.
- Wire POST /api/v1/chat with SSE events.
- Metrics: agent_requests_total, agent_latency_seconds, agent_tool_calls_total, agent_tokens_total,
  agent_cost_usd_total, agent_verification_failures_total, rag_retrieval_top_score, rag_empty_results_total.
- Tests with a mocked OpenAI client:
  (1) "Where should I open a bakery in Fergana?" → calculate_business_score is called
  (2) a question with no data → the insufficient-data sentence
  (3) the verifier catches an invented number
  (4) fallback mode works without a key
  (5) Uzbek and Russian questions are answered in the same language.
Stop and summarise.
```

---

## Phase 9 — Frontend: dashboard, 3D map, AI chat

### Pages
1. **Home** — large "Ask AI anything about business…" input with example chips, 3D map preview, KPI strip.
2. **Map** — deck.gl over MapLibre: regions as extruded `GeoJsonLayer` (height + colour = metric),
   districts as `ColumnLayer` (approx centroids rendered translucent), hover tooltip with source,
   click → side panel, metric selector, year slider (history solid, forecast years marked),
   2D/3D toggle. Mapbox style only if `MAPBOX_TOKEN` is set; otherwise a free MapLibre style.
3. **Recommend** — form (business type, region, budget, target); ranked list with stacked
   contribution bars, rank range, coverage, "View on map", "Compare".
4. **Regional analytics** — ranking table, trends, sector mix.
5. **Forecast** — history line + dashed forecast + 80/95% bands; model name and backtest MAPE.
6. **AI chat** — SSE streaming, live tool-call chips ("Fetching population…"), answers drive the
   map via `map_focus`, inline charts, 👍/👎 feedback.
7. **Monitoring** — data freshness, model metrics, agent stats; links to Grafana.

Global banner when any shown value is synthetic: "DEMO / SYNTHETIC DATA — not official statistics".
Languages: English (default), Uzbek, Russian (i18next).

### Design direction
- Palette inspired by Registan tilework: lapis `#1F3F7A`, turquoise `#3FB8AF`, saffron `#E3A72F`,
  pomegranate `#C8423A` (risk), background `#F3F5F7`, text `#1A2433`; dark mode background `#16233B`.
- One typeface with Latin + Cyrillic support (e.g. Onest), clear type scale.
- The 3D map is the hero; everything else is calm and orderly.
- Responsive, visible keyboard focus, respects `prefers-reduced-motion`.

### Prompt
```
Read CLAUDE.md and PLAN.md. Implement Phase 9.
- React + Vite + TS, react-router, TanStack Query, deck.gl + react-map-gl/maplibre, Recharts, i18next.
- All 7 pages and the design direction from PLAN.md Phase 9.
- Synthetic banner driven by meta.is_synthetic.
- Chat map_focus triggers flyTo on the map.
- Production build served by nginx; /api proxied to backend.
- Playwright e2e: home loads; recommend form returns results; map renders regions; chat streams a reply
  (backend in fallback mode).
Stop and summarise with screenshots saved to docs/screenshots/.
```

---

## Phase 10 — Monitoring

### Metrics (Prometheus)

| Metric | Type | Labels |
|---|---|---|
| `http_requests_total`, `http_request_duration_seconds` | counter / histogram | route, status |
| `agent_requests_total`, `agent_latency_seconds` | counter / histogram | intent, status, lang |
| `agent_tool_calls_total`, `agent_tool_latency_seconds` | counter / histogram | tool, status |
| `agent_tokens_total`, `agent_cost_usd_total` | counter | kind, model |
| `agent_verification_failures_total` | counter | — |
| `rag_retrieval_top_score`, `rag_empty_results_total` | histogram / counter | — |
| `mcp_tool_calls_total`, `mcp_tool_latency_seconds` | counter / histogram | tool, status |
| `recommendation_requests_total`, `recommendation_score` | counter / histogram | business_type |
| `recommendation_low_coverage_total` | counter | business_type |
| `ingestion_runs_total`, `ingestion_rows_total` | counter | source, status/result |
| `data_last_update_timestamp` | gauge | source |
| `data_quality_check_passed` | gauge | check |
| `data_missing_ratio` | gauge | indicator |
| `model_backtest_smape` | gauge | indicator, level, model |
| `feature_drift_psi` | gauge | feature |
| `prediction_realized_error` | gauge | indicator |
| `recommendation_stability_jaccard` | gauge | business_type |
| `user_feedback_total` | counter | rating |

Batch-job metrics are written to the DB by jobs and exported as gauges by the backend's
`/metrics` (no Pushgateway).

### Drift & stability
- Feature drift: PSI between the previous and the latest year per feature; PSI > 0.2 → alert.
- Prediction drift: when a new year arrives, realised error of last year's forecast (`split=live`).
- Recommendation stability: top-5 Jaccard for fixed reference queries across runs + Monte Carlo rank width.

### Grafana dashboards (provisioned JSON)
1. **Data Health** — freshness, row counts, missing-ratio heatmap (indicator × region), failed ingests, quality checks.
2. **ML Models** — sMAPE/MAE per model × indicator vs baseline, PSI, realised error.
3. **Recommendations** — score distributions, most-recommended districts, stability, feedback.
4. **Agent** — requests/min, p50/p95 latency, tool calls & failures, tokens & cost, verification failures, RAG empties; recent runs table from Postgres.
5. **API / Infra** — RPS, error rate, Postgres connections.

### Alerts (`monitoring/prometheus/alerts.yml`)
- 2 consecutive failed ingests · data older than 45 days · agent error rate > 10% (5 min) ·
  agent p95 > 20 s · PSI > 0.2 · backtest sMAPE 20% worse than the previous model version.

### Tracing (optional)
OpenTelemetry (FastAPI, httpx, SQLAlchemy, agent spans) → OTLP → Langfuse or Jaeger
via `docker-compose.observability.yml`; enabled with `OTEL_ENABLED=true`.

### Prompt
```
Read CLAUDE.md and PLAN.md. Implement Phase 10.
- backend/app/core/metrics.py defines every metric in one place; wire into agent, MCP,
  recommendations and pipelines.
- monitoring/drift.py (PSI, realised error, stability) + manage.py monitor.
- 5 Grafana dashboards as JSON under monitoring/grafana/dashboards, auto-provisioned.
- monitoring/prometheus/alerts.yml + rule_files in prometheus.yml.
- /api/v1/monitoring/* endpoints for the frontend monitoring page.
- docs/monitoring.md explaining every metric and dashboard.
Stop and summarise.
```

### Verify
```powershell
python manage.py monitor
# ask a few questions in the chat, then:
start http://localhost:3000/dashboards
start http://localhost:9090/alerts
```

---

## Phase 11 — Evaluation

### Recommendation quality
- `tests/eval/reco_gold.yaml`: ≥ 30 queries with expert-labelled relevance (0–3) per district.
  Labels must come from independent judgement (local knowledge, market observation, expert interview),
  **not** from the scoring features, otherwise the evaluation is circular. State this in the report.
- Metrics: Precision@K, Recall@K, NDCG@K (K = 3, 5), MRR.
- Baselines: population-only ranking, random ranking.
- Ablation: drop each factor → ΔNDCG@5.

### Forecast quality
Backtest leaderboard from Phase 5; % improvement over `naive_last`.

### Agent quality
- `tests/eval/agent_cases.yaml`: 25 questions (en/uz/ru) with expected tools and answer properties.
- Metrics: tool-selection accuracy, task success, numeric faithfulness, correct "insufficient data"
  detection, latency, tokens, cost.
- RAG: 20 methodology questions → hit@5 and citation presence.

### Prompt
```
Read CLAUDE.md and PLAN.md. Implement Phase 11.
- ml/evaluation/ranking_metrics.py (P@K, R@K, NDCG@K, MRR) with unit tests against known values.
- ml/evaluation/run_reco_eval.py, run_forecast_eval.py, run_agent_eval.py, run_rag_eval.py.
- Results → model_metrics and MLflow; docs/evaluation_report.md generated automatically with tables.
- Create reco_gold.yaml and agent_cases.yaml templates with 5 filled examples each and TODO markers
  for the rest (I will label them).
- manage.py eval runs everything.
Stop and summarise.
```

---

## Phase 12 — Hardening & one-command launch

### Prompt
```
Read CLAUDE.md and PLAN.md. Implement Phase 12.
- manage.py demo: up → wait for health → ingest (uses cached raw files if SIAT is unreachable) →
  seed → features → train → eval → print URLs.
- Offline mode: if SIAT is unreachable, load from data/processed/ snapshot committed as
  data/snapshot/*.csv.gz (small, official data only) so a clean machine can demo without internet.
- Startup checks: missing .env values produce a clear message; missing OPENAI key → fallback banner.
- Backups: manage.py backup / restore (pg_dump into ./backups).
- Security: no secrets in logs, input validation on all endpoints, nginx security headers.
- Performance: indexes verified with EXPLAIN on the 5 heaviest queries; /geo responses < 300 ms.
- Run the full test suite + Playwright e2e in CI.
- Clean-machine test: document every step in docs/runbook.md.
Stop and summarise.
```

### Verify (clean machine)
```powershell
git clone <repo> ; cd <repo>
copy .env.example .env
python -m venv .venv ; .\.venv\Scripts\Activate.ps1 ; pip install typer
python manage.py demo
```

---

## Phase 13 — Documentation & presentation

### Prompt
```
Read CLAUDE.md and PLAN.md. Implement Phase 13.
- docs/architecture.md with Mermaid: component diagram, data flow, agent sequence, deployment.
- docs/research_questions.md mapping each research question to experiments and metrics.
- docs/limitations.md: annual frequency, short services series (2020+), no district-level income,
  approximate district geometry, synthetic gap-fill, score = decision support not guarantee,
  gold labels are expert judgement.
- docs/demo_script.md: 5-minute demo ("700 million UZS bakery in Fergana": chat → recommendation →
  map → forecast → sources → monitoring).
- docs/weekly_report_template.md for internship reporting.
- Final README.md: overview, screenshots, architecture diagram, quick start, DATA_MODE, commands.
Stop and summarise.
```

---

## Appendix A — SIAT dataset → internal indicator map

All verified by download: 0 failed quality checks.

### District level (also region + country)
| SIAT id | Internal code | Unit in source → stored | Years | Additive |
|---|---|---|---|---|
| 246 | `population_total` | thousand people → persons | 2010–2026 | yes |
| 248 | `population_urban` | thousand people → persons | 2010–2026 | yes |
| 247 | `population_rural` | thousand people → persons | 2010–2026 | yes |
| 2044 | `enterprises_active` | units | 2017–2026 | yes |
| 2046 | `enterprises_registered` | units | 2017–2026 | yes |
| 2049 | `enterprises_new` | units | 2016–2025 | yes |
| 4482 | `market_services_volume` | bln UZS → UZS | 2020–2025 | yes |
| 4483 | `market_services_growth` | % of previous year | 2020–2025 | no |
| 3414 | `market_services_per_capita` | thsd UZS → UZS | 2020–2025 | no |
| 4464 | `trade_services_volume` | bln UZS → UZS | 2020–2025 | yes |
| 4465 | `trade_services_growth` | % of previous year | 2020–2025 | no |
| 4462 | `food_services_volume` (accommodation & food) | bln UZS → UZS | 2020–2025 | yes |
| 4463 | `food_services_growth` | % of previous year | 2020–2025 | no |
| 4470 | `health_services_volume` | bln UZS → UZS | 2020–2025 | yes |
| 4471 | `health_services_growth` | % of previous year | 2020–2025 | no |
| 4468 | `education_services_volume` | bln UZS → UZS | 2020–2025 | yes |
| 4469 | `education_services_growth` | % of previous year | 2020–2025 | no |
| 4460 | `transport_services_volume` | bln UZS → UZS | 2020–2025 | yes |
| 4461 | `transport_services_growth` | % of previous year | 2020–2025 | no |
| 1418 | `hospitals` | units | 2010–2025 | yes |
| 1362 | `outpatient_clinics` | units | 2010–2025 | yes |
| 307 | *(reference only: 1 = district, 0 = city)* | — | — | — |

### Region level only
| SIAT id | Internal code | Unit | Notes |
|---|---|---|---|
| 1582 | `grp_quarterly` → `grp_annual` | bln UZS current prices | check cumulative vs discrete |
| 1588 | `gva_services_quarterly` | bln UZS | |
| 1589 | `gva_trade_food_quarterly` | bln UZS | |
| 1840 | `small_business_share_gva` | % of GVA | 2015–2025 |
| 1777 | `services_growth_quarterly` | % y/y | |
| 1780 | `trade_food_growth_quarterly` | % y/y | |
| 4116–4119 | `population_{urban,rural}_{women,men}` | thousand people | region only |

### National level only
| SIAT id | Internal code | Use |
|---|---|---|
| 1820 | `deflator_services` | real growth |
| 1825 | `deflator_trade_food` | real growth |

### Ignored
570, 578, 583, 597 (FISIM, NPISH consumption — national only, not business-relevant);
1584–1587, 1773, 1775, 1778, 1783, 1786, 1801–1815, 1829, 1834, 1869–1871 (keep raw, not mapped yet).

### Known source issues
- Dataset 1871 contains period `2025-Q5` — skipped by the parser.
- Dataset 4117/4119 cover 13 of 14 regions.

### Still missing (gap-fill or search later)
- Average monthly wage / household income by region (search: `average monthly wage`, `nominal wage`,
  `o'rtacha oylik`). If found only at region level, broadcast as region context, never as district fact.
- Age structure by district (search: `age`, `yosh`, `возраст`) — useful for pharmacy, clinic, education.
- Retail trade turnover by district (search: `retail trade turnover`, `chakana savdo`).

Command to search and add:
```powershell
python pipelines/siat_ingest.py search "average monthly wage"
python pipelines/siat_ingest.py fetch --ids <id>
# then add the id to data/reference/indicator_map.yaml and run: python manage.py ingest
```

---

## Appendix B — Research questions → evidence

| # | Question | Evidence |
|---|---|---|
| 1 | How well can official statistics be turned into business features? | Feature coverage table, ablation (Phases 3, 11) |
| 2 | Can an agent autonomously select and combine statistical tools and models? | Tool-selection accuracy, task success (Phase 11) |
| 3 | How accurately can business indicators be forecast? | Backtest leaderboard vs naive (Phase 5) |
| 4 | How effective are the location recommendations? | P@K, R@K, NDCG@K vs baselines (Phase 11) |
| 5 | How can quality be monitored continuously? | Metrics, drift, dashboards, alerts (Phase 10) |
| 6 | Does geospatial visualisation improve decisions? | Small user study (5–8 people): time-to-decision and confidence with vs without map |

---

## Appendix C — Working with Claude Code

- Start each phase with: `Read CLAUDE.md and PLAN.md. Implement Phase N. Show me the plan first.`
- Do not accept "done" without test output: ask `Run python manage.py test and show the result.`
- If context gets long: `/compact`. New phase: `/clear` (CLAUDE.md is re-read automatically).
- If Claude Code tries to rewrite `siat_ingest.py`, stop it — it is a working, verified asset.
- If SIAT is blocked from inside Docker, run `python pipelines/siat_ingest.py fetch ...` on the host
  (it writes to `./data`, which is mounted into the containers) and then `python manage.py ingest --no-download`.
