# Uzbekistan Smart Business Intelligence

An agentic AI platform that turns official SIAT / Stat.uz statistics into data-backed
business location recommendations for Uzbekistan.

```
SIAT download → warehouse → features → forecasts → Business Opportunity Score
→ MCP tools → AI agent + RAG → dashboard + 3D map + chat → monitoring + evaluation
```

Project rules: [`CLAUDE.md`](CLAUDE.md) · Build plan (phases 0–13): [`PLAN.md`](PLAN.md)

## Status

| Phase | State |
|---|---|
| SIAT ingest (`pipelines/siat_ingest.py`) | ✅ working |
| 0 — Repository, Docker, task runner | ✅ done |
| 1 — Warehouse (lean): 26 indicators, 14 regions, 208 districts/cities, 43.5k observations | ✅ done |
| 6 — API (lean): overview, indicators, regions, statistics, timeseries | ✅ done |
| 9 — Dashboard (lean): KPIs, ranking chart + table, trends | ✅ done |
| 2–5, 7–8, 10–13 | ⏳ planned |

## Quick start — local, no Docker (Windows PowerShell)

Requirements: Python 3.11+, Node 20+, portable PostgreSQL in `.tools/` (see below).

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e "backend[dev]" "mcp>=1.9,<2" typer
copy .env.example .env

python manage.py db-init               # first time only
python manage.py ingest --local        # download SIAT data + migrate + load (≈1 min)
python manage.py dev                   # database + API + UI → http://localhost:5174
```

## Quick start — Docker

Requirements: Docker Desktop.

```powershell
# 1. Python environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e "backend[dev]" "mcp>=1.9,<2" typer

# 2. Configuration
copy .env.example .env          # add OPENAI_API_KEY if you have one (optional)

# 3. Start the stack
python manage.py up             # docker compose up -d --build
python manage.py ps             # every service should be "healthy"
```

| Service | URL |
|---|---|
| Frontend | http://localhost:5173 |
| API + docs | http://localhost:8000/docs · http://localhost:8000/health |
| MCP server | http://localhost:8100/mcp |
| Grafana | http://localhost:3000 (admin / admin) |
| Prometheus | http://localhost:9090 |
| MLflow | http://localhost:5000 |

## Official data (SIAT)

```powershell
python pipelines/siat_ingest.py selftest                   # offline parser test
python pipelines/siat_ingest.py search "average monthly wage"
python pipelines/siat_ingest.py fetch --ids 246 2044 4482  # writes to ./data
python pipelines/siat_ingest.py report                     # region/district coverage
```

Outputs: `data/raw/siat/` (raw JSON + sha256), `data/processed/*.csv`, `data/siat.db` (SQLite).

## Commands

```powershell
python manage.py up | down | ps | logs [service]
python manage.py dev            # local: db + API (:8000) + UI (:5174)
python manage.py ingest --local # SIAT → Postgres (--no-download to reuse cached raw files)
python manage.py migrate        # alembic upgrade head
python manage.py test           # pytest (integration tests skip if the DB is not loaded)
python manage.py lint [--fix]   # ruff
python manage.py selftest       # SIAT parser test
python manage.py seed | features | train | eval | monitor | demo          # added phase by phase
```

## Local development without Docker

PostgreSQL 16 + PostGIS run from a portable copy in `.tools/pgsql` (no admin rights needed; not in git).
To set it up on a new machine, unzip the EDB binaries
(`postgresql-16.x-windows-x64-binaries.zip`) into `.tools/` and copy the PostGIS bundle
(`postgis-bundle-pg16-3.x.zip` from download.osgeo.org) `bin/ lib/ share/` over `.tools/pgsql/`.

```powershell
python manage.py db-init      # first time: cluster + sbi/mlflow databases + postgis (idempotent)
python manage.py db-start     # after every reboot
python manage.py db-status | db-stop | db-psql
```

pgvector is not available in this mode, so RAG falls back to BM25 (CLAUDE.md rule 10).

```powershell
uvicorn app.main:app --app-dir backend --reload --port 8000   # API
python -m mcp_server.server                                   # MCP (streamable-http :8100)
cd frontend; npm install; npm run dev                         # UI on :5173, proxies /api to :8000
```

Without a running Postgres, `/health` returns `503 {"status":"degraded","db":"down"}`. That is expected.

## Repository layout

```
backend/      FastAPI app (app/api, app/services, app/db, app/core) + Alembic
mcp_server/   FastMCP server (stdio + streamable-http)
agents/ rag/ ml/          agent, retrieval, features/scoring/forecasting/evaluation
pipelines/    siat_ingest.py (+ loaders in later phases)
data/         raw/, processed/, reference/, docs/
monitoring/   prometheus/, grafana/, mlflow/
frontend/     React + Vite + TypeScript
tests/        unit/, integration/, eval/
db/           Postgres 16 + PostGIS + pgvector image
manage.py     task runner (Typer)
```
