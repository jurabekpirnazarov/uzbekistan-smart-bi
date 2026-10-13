# Runbook

Two ways to run the platform. Both work on Windows + PowerShell.

## A. Local, without Docker (no admin rights needed)

Requirements: Python 3.11+ and Node.js 20+.

```powershell
git clone https://github.com/jurabekpirnazarov/uzbekistan-smart-bi.git
cd uzbekistan-smart-bi
copy .env.example .env                  # optional: put OPENAI_API_KEY=... in .env
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".\backend[dev,mlflow]" typer "mcp>=1.9,<2"
```

PostgreSQL 16 + PostGIS run portably from `.tools\` (no installer, no admin):

1. Download the PostgreSQL 16 Windows **zip** (EDB "binaries") and unpack it so that
   `.tools\pgsql\bin\pg_ctl.exe` exists.
2. Download the matching PostGIS bundle zip from download.osgeo.org (`postgis-bundle-pg16-*.zip`) and copy
   its `bin`, `lib` and `share` folders over `.tools\pgsql\`. (On networks that block certificate
   revocation checks use `curl --ssl-no-revoke`.)

Then:

```powershell
python manage.py db-init        # cluster in .tools\pgdata, databases sbi + mlflow, PostGIS
python manage.py demo           # ingest (cached SIAT files or download) → seed → features → train → monitor → eval
python manage.py dev            # database + API :8000 + app :5174 + MCP :8100 + MLflow :5000
```

Open http://localhost:5174. `Ctrl+C` stops the app; `python manage.py db-stop` stops the database.

## B. Docker (server)

```powershell
copy .env.example .env
docker compose up -d --build
docker compose run --rm worker python manage.py demo
```

App http://localhost:8080 · API http://localhost:8000/docs · Grafana http://localhost:3000 ·
Prometheus http://localhost:9090 · MLflow http://localhost:5000 · MCP http://localhost:8100/mcp

## Automatic data refresh

`python manage.py refresh` downloads new SIAT data and rebuilds what depends on it:

download (only datasets whose SIAT catalog date changed) → migrate → load (idempotent upsert) →
*if any dataset content changed:* features → forecasts → RAG index → monitoring.

Every run is stored in `pipeline_runs` (shown on the Monitoring page) and logged to `logs/refresh-YYYYMMDD.log`;
a lock file prevents parallel runs. `--force` recomputes even without new data.

| Where | How it is scheduled |
|---|---|
| This Windows machine | `python manage.py schedule` registers the task *Uzbekistan Smart BI - data refresh* in Windows Task Scheduler for the current user (no admin). Default: every 3 days at 03:00 (`REFRESH_EVERY_DAYS`, `REFRESH_AT` in `.env`, or `--every-days 2 --at 04:30`). A run missed while the computer was off starts when it is back on. `--status` shows the next run, `--remove` deletes the task. |
| Docker / server | The `scheduler` service runs `python manage.py scheduler`: it computes the next run from the last successful run in `pipeline_runs`, so container restarts do not cause extra downloads. |
| Linux without Docker | cron: `0 3 */3 * * cd /path/to/repo && .venv/bin/python manage.py refresh --trigger schedule` |

Alert `RefreshOverdue` fires when no refresh succeeded for 7 days.

## Everyday tasks

| Task | Command |
|---|---|
| Refresh everything now (download → rebuild) | `python manage.py refresh` |
| Download + load only | `python manage.py ingest --local` |
| Rebuild geography + RAG index | `python manage.py seed --local` |
| Recompute features | `python manage.py features --local` |
| Retrain forecasts | `python manage.py train --local` |
| Monitoring snapshot | `python manage.py monitor --local` |
| Evaluation report | `python manage.py eval --local` → `docs/evaluation_report.md` |
| Tests / lint | `python manage.py test` · `python manage.py lint` |
| Backup / restore | `python manage.py backup` · `python manage.py restore` |
| Regenerate docs | `python -m ml.features.docs` · `python -m app.api.docs_gen` |
| Regenerate Grafana dashboards | `python monitoring/grafana/build_dashboards.py` |

`--local` is optional when Docker is not installed (jobs then run on the host automatically).

## Startup checks and failure modes

| Symptom | Cause / fix |
|---|---|
| Status pill says "Database offline" | `python manage.py db-start`; log in `.tools\postgres.log` |
| Chat header says "Rule-based mode (no OpenAI key)" | No `OPENAI_API_KEY` in `.env` — the rule-based agent answers; add a key and restart for the LLM |
| "No features computed yet" | `python manage.py features --local` |
| Forecast page: "No forecast" | `python manage.py train --local` |
| Map has no basemap (grey background) | No internet for the free CARTO tiles; the data layers still work |
| Port 5174 busy | `python manage.py dev --port 5175` |
| Chat returns "Too many requests" | Rate limit is 20 chat requests per minute per IP |

## Security notes

Secrets only in `.env` (git-ignored). Logs never contain the OpenAI key or prompts' secrets. All endpoints
validate input with Pydantic; errors use `{code, message, details}`. The nginx config of the Docker frontend
adds standard security headers.
