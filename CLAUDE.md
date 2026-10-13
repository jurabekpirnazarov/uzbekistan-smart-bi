# CLAUDE.md — Uzbekistan Smart Business Intelligence

Persistent rules for Claude Code. Read automatically every session.
The step-by-step build plan is in `PLAN.md`. Work on **one phase at a time**:
plan → implement → run tests → summarise → stop.

## What we are building

An agentic AI platform that turns official SIAT / Stat.uz statistics into
data-backed business location recommendations for Uzbekistan:

SIAT download → structured warehouse → features → forecasts →
Business Opportunity Score → MCP tools → AI agent + RAG →
dashboard + 3D map + chat → monitoring + evaluation.

## Current state (already done — do not redo)

- `pipelines/siat_ingest.py` — working SIAT downloader + normaliser. Reuse it, do not rewrite it.
  - Catalog: `GET https://siat.stat.uz/api/sdmx/json/` (3,236 datasets)
  - Dataset: `GET https://siat.stat.uz/media/uploads/sdmx/sdmx_data_{id}.json`
  - CLI: `catalog`, `search`, `fetch --ids/--query/--preset`, `rebuild`, `report`, `selftest`
  - Outputs: `data/raw/siat/` (raw JSON + sha256 meta), `data/processed/{catalog,indicators,observations,regions,ingestion_log}.csv`,
    `data/processed/quality_report.json`, `data/siat.db` (SQLite).
- 56 datasets downloaded, 58,409 observations, 0 failed quality checks.
- District-level official data exists for population, enterprises, services by sector and health facilities.
  The dataset → internal-code map is in `PLAN.md`, Appendix A.

## Architecture (extend, do not restructure)

```
frontend (React + Vite + TS, deck.gl/MapLibre, Recharts)
   │ HTTP / SSE
backend (FastAPI) ──► app/services/   ← the ONLY place business logic lives
   │                     ▲        ▲
agents/ (OpenAI tools) ──┘        └── mcp_server/ (FastMCP; calls the same services)
rag/ (pgvector + BM25)        ml/ (features, scoring, forecasting, evaluation)
PostgreSQL 16 + PostGIS + pgvector
monitoring: Prometheus + Grafana + MLflow + agent_runs tables
```

FastAPI routers, MCP tools and agent tools are thin wrappers over `app/services/` and `ml/`.
Never duplicate calculation logic.

## Repository layout

```
backend/      FastAPI app: app/api, app/services, app/db, app/core
mcp_server/   FastMCP server (stdio + streamable-http)
agents/       orchestrator, tool registry, prompts, fallback planner
rag/          ingest, chunking, embeddings, hybrid retrieval
ml/           features/, scoring/, forecasting/, evaluation/, profiles/*.yaml
pipelines/    siat_ingest.py, load_siat.py, load_reference.py, generate_synthetic.py
data/         raw/, processed/, reference/, docs/ (RAG sources)
monitoring/   prometheus/, grafana/provisioning/, grafana/dashboards/, drift.py
frontend/     React app
tests/        unit/, integration/, eval/
docs/         architecture, data dictionary, features, mcp, monitoring, evaluation, limitations
manage.py     cross-platform task runner (Typer) — works on Windows without make
```

## Non-negotiable rules

1. **The LLM never computes numbers.** Growth, shares, per-capita values, scores and forecasts
   are computed in Python. The LLM only explains tool outputs.
2. **No invented statistics.** If data is missing the agent says:
   "I don't have sufficient official data to answer this reliably."
3. **Every value is traceable**: `dataset_id`, `indicator_code`, `period`, `unit`, `source_url`,
   `retrieved_at`, `is_synthetic`.
4. **Synthetic data is never presented as official.** Anything with `is_synthetic=true` carries a
   "DEMO / SYNTHETIC DATA" label in the UI and in agent answers.
5. **Three layers stay separate** in every answer: Official statistic / Model prediction / AI interpretation.
6. **"Business Opportunity Score"** is an analytical model, not truth. Always show the factor breakdown.
7. **Internal indicator codes only.** Feature, scoring and agent code use codes from
   `data/reference/indicator_map.yaml` (e.g. `population_total`), never raw SIAT dataset ids.
8. **Units are normalised once, in the loader**: people (not thousands), UZS (not bln/thsd).
   Growth-rate datasets ("% of previous year") are stored as-is and never summed.
9. **Secrets only from `.env`**: `OPENAI_API_KEY`, `DATABASE_URL`, `VECTOR_DB_URL`, `MAPBOX_TOKEN`.
10. **Works without an OpenAI key**: the agent falls back to a rule-based planner, RAG to BM25.
11. **New business type = new YAML profile. New indicator = new row in `indicator_map.yaml`.**
    Neither requires code or schema changes.

## Code style

- Python 3.11, type hints, Pydantic v2, SQLAlchemy 2.0, Alembic.
- `ruff` + `ruff format`; `mypy` on `backend/app/services` and `ml/`.
- `structlog` JSON logs with `request_id`.
- Every service function has a pytest test. A phase is not done until tests pass.
- Frontend: TypeScript, functional components, one API client in `src/api/`.

## Environment

- The developer uses **Windows + PowerShell + Docker Desktop**. Every documented command must work there.
- Task runner: `python manage.py <task>`. A `Makefile` may exist as a thin alias for CI only.
- Add `.gitattributes` (`* text=auto eol=lf`) so shell scripts work inside Linux containers.
- Local virtualenv: `.venv/`. Never commit `data/raw/`, `.env`, `.venv/`.

## Commands

```powershell
docker compose up -d --build        # start everything
python manage.py ingest             # SIAT download (ids from indicator_map.yaml) + load into Postgres
python manage.py seed               # reference data, geo boundaries, synthetic gap-fill, RAG index
python manage.py features           # compute features
python manage.py train              # forecasting models → MLflow
python manage.py eval               # recommendation, forecast, agent, RAG evaluation
python manage.py monitor            # drift + data-quality metrics
python manage.py test               # pytest
python manage.py demo               # ingest + seed + features + train in one go
```

## Definition of done (every phase)

- `docker compose up -d --build` works on a clean machine.
- `python manage.py test` passes.
- New endpoints / tools / metrics are documented in `docs/`.
- New metrics appear on `/metrics`.
- End with a short summary: what was built, how to verify it, known limitations.
