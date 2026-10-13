#!/usr/bin/env python3
"""Cross-platform task runner (works on Windows PowerShell without make).

    python manage.py up | down | logs | ps                       (Docker)
    python manage.py dev                                         (no Docker: everything on this machine)
    python manage.py ingest | seed | features | train | eval | monitor | demo
    python manage.py backup | restore | test | lint | selftest

Jobs that need the database run inside the worker container (`docker compose run --rm worker ...`)
when Docker is available, otherwise on the host. --local forces the host.
Only `typer` is required on the host to use this file.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import typer

ROOT = Path(__file__).resolve().parent
app = typer.Typer(add_completion=False, no_args_is_help=True, help="Uzbekistan Smart BI task runner")

PY = sys.executable


def run(cmd: list[str], check: bool = True) -> int:
    typer.secho("$ " + " ".join(cmd), fg=typer.colors.BRIGHT_BLACK)
    code = subprocess.call(cmd, cwd=ROOT)
    if check and code != 0:
        raise typer.Exit(code)
    return code


def compose(*args: str) -> list[str]:
    if shutil.which("docker") is None:
        typer.secho(
            "Docker was not found. Install Docker Desktop: https://www.docker.com/products/docker-desktop/",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)
    if not (ROOT / ".env").exists():
        typer.secho("No .env file. Run: copy .env.example .env", fg=typer.colors.RED)
        raise typer.Exit(1)
    return ["docker", "compose", *args]


def docker_available() -> bool:
    return shutil.which("docker") is not None


def job(args: list[str], local: bool) -> None:
    """Run a Python job in the worker container, or on the host (--local, or when Docker is missing)."""
    if local or not docker_available():
        env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT), str(ROOT / "backend")])}
        env.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
        env.setdefault("PYTHONIOENCODING", "utf-8")  # job output has non-ASCII; never crash on cp1251 consoles
        typer.secho("$ " + " ".join([PY, *args]), fg=typer.colors.BRIGHT_BLACK)
        code = subprocess.call([PY, *args], cwd=ROOT, env=env)
        if code != 0:
            raise typer.Exit(code)
    else:
        run(compose("run", "--rm", "worker", "python", *args))


def not_yet(phase: int) -> None:
    typer.secho(f"Not implemented yet - arrives in Phase {phase} (see PLAN.md).", fg=typer.colors.YELLOW)
    raise typer.Exit(1)


# --- local database (no Docker) ------------------------------------------------
# Portable PostgreSQL 16 + PostGIS unpacked in .tools/pgsql; data lives in .tools/pgdata.

PG_BIN = ROOT / ".tools" / "pgsql" / "bin"
PG_DATA = ROOT / ".tools" / "pgdata"
PG_LOG = ROOT / ".tools" / "postgres.log"
PG_PORT = "5432"
PG_USER, PG_PASSWORD, PG_DB = "postgres", "postgres", "sbi"


def pg(tool: str) -> str:
    # English tool messages regardless of the Windows locale (avoids mis-encoded output).
    os.environ["LC_MESSAGES"] = "C"
    os.environ["PGPASSWORD"] = PG_PASSWORD
    exe = PG_BIN / f"{tool}.exe" if sys.platform == "win32" else PG_BIN / tool
    if not exe.exists():
        typer.secho(
            f"{exe} not found. Portable PostgreSQL is expected in .tools/pgsql (see README).", fg=typer.colors.RED
        )
        raise typer.Exit(1)
    return str(exe)


def psql(sql: str, db: str = "postgres", check: bool = True) -> int:
    return run(
        [
            pg("psql"),
            "-h",
            "localhost",
            "-p",
            PG_PORT,
            "-U",
            PG_USER,
            "-d",
            db,
            "-v",
            "ON_ERROR_STOP=1",
            "-qAt",
            "-c",
            sql,
        ],
        check=check,
    )


@app.command("db-init")
def db_init() -> None:
    """Create the local cluster, the sbi + mlflow databases and the extensions (idempotent)."""
    if not (PG_DATA / "PG_VERSION").exists():
        pwfile = ROOT / ".tools" / "pwfile.tmp"
        pwfile.write_text(PG_PASSWORD, encoding="utf-8")
        try:
            run(
                [
                    pg("initdb"),
                    "-D",
                    str(PG_DATA),
                    "-U",
                    PG_USER,
                    "--pwfile",
                    str(pwfile),
                    "-E",
                    "UTF8",
                    "--locale=C",
                    "--auth=scram-sha-256",
                ]
            )
        finally:
            pwfile.unlink(missing_ok=True)
    db_start()
    for name in (PG_DB, "mlflow"):
        exists = subprocess.run(
            [
                pg("psql"),
                "-h",
                "localhost",
                "-p",
                PG_PORT,
                "-U",
                PG_USER,
                "-d",
                "postgres",
                "-qAt",
                "-c",
                f"SELECT 1 FROM pg_database WHERE datname = '{name}'",
            ],
            capture_output=True,
            text=True,
        ).stdout.strip()
        if exists != "1":
            psql(f"CREATE DATABASE {name}")
    psql("CREATE EXTENSION IF NOT EXISTS postgis", db=PG_DB)
    if psql("CREATE EXTENSION IF NOT EXISTS vector", db=PG_DB, check=False) != 0:
        typer.secho(
            "pgvector is not available locally - RAG will use BM25 only (allowed by CLAUDE.md rule 10).",
            fg=typer.colors.YELLOW,
        )
    psql("SELECT 'postgis ' || postgis_version()", db=PG_DB)


@app.command("db-start")
def db_start() -> None:
    """Start the local PostgreSQL server (no-op if it is already running)."""
    if subprocess.call([pg("pg_ctl"), "status", "-D", str(PG_DATA)], stdout=subprocess.DEVNULL) == 0:
        typer.secho(f"PostgreSQL is already running on localhost:{PG_PORT}", fg=typer.colors.GREEN)
        return
    # The server inherits pg_ctl's handles: detach them, otherwise a piped caller never sees EOF.
    code = subprocess.call(
        [pg("pg_ctl"), "start", "-D", str(PG_DATA), "-l", str(PG_LOG), "-w", "-o", f"-p {PG_PORT}"],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if code != 0:
        typer.secho(f"PostgreSQL failed to start - see {PG_LOG}", fg=typer.colors.RED)
        raise typer.Exit(code)
    typer.secho(f"PostgreSQL running on localhost:{PG_PORT} (log: {PG_LOG.relative_to(ROOT)})", fg=typer.colors.GREEN)


@app.command("db-stop")
def db_stop() -> None:
    """Stop the local PostgreSQL server."""
    run([pg("pg_ctl"), "stop", "-D", str(PG_DATA), "-m", "fast"], check=False)


@app.command("db-status")
def db_status() -> None:
    """Show whether the local PostgreSQL server is running."""
    run([pg("pg_ctl"), "status", "-D", str(PG_DATA)], check=False)


@app.command("db-psql")
def db_psql() -> None:
    """Open an interactive psql shell on the sbi database."""
    run([pg("psql"), "-h", "localhost", "-p", PG_PORT, "-U", PG_USER, "-d", PG_DB], check=False)


# --- stack -----------------------------------------------------------------


@app.command()
def up(build: bool = typer.Option(True, help="rebuild images")) -> None:
    """Start every service (docker compose up -d)."""
    run(compose("up", "-d", *(["--build"] if build else [])))
    run(compose("ps"))


@app.command()
def down(volumes: bool = typer.Option(False, "--volumes", help="also delete data volumes")) -> None:
    """Stop every service."""
    run(compose("down", *(["-v"] if volumes else [])))


@app.command()
def ps() -> None:
    """Show service status and health."""
    run(compose("ps"))


@app.command()
def logs(service: str = typer.Argument(None), follow: bool = typer.Option(True, "--follow/--no-follow")) -> None:
    """Show logs (all services or one)."""
    run(compose("logs", *(["-f"] if follow else []), "--tail", "200", *([service] if service else [])), check=False)


# --- data & models -----------------------------------------------------------


def mapped_dataset_ids() -> list[str]:
    import yaml

    m = yaml.safe_load((ROOT / "data" / "reference" / "indicator_map.yaml").read_text(encoding="utf-8"))
    ids = [s["siat_dataset_id"] for s in m["indicators"].values()]
    ids += [r["siat_dataset_id"] for r in (m.get("reference") or {}).values()]
    return [str(i) for i in sorted(set(ids))]


@app.command()
def migrate(local: bool = typer.Option(True, help="run on the host (default) or in the worker")) -> None:
    """Apply database migrations (alembic upgrade head)."""
    job(["-m", "alembic", "-c", "backend/alembic.ini", "upgrade", "head"], local)


@app.command()
def ingest(
    local: bool = typer.Option(False, help="run on the host instead of the worker container"),
    download: bool = typer.Option(True, help="download/refresh datasets from SIAT first (cached files are reused)"),
) -> None:
    """SIAT download (ids from indicator_map.yaml) + migrate + load into Postgres."""
    if download:
        job(["pipelines/siat_ingest.py", "fetch", "--ids", *mapped_dataset_ids()], local)
    migrate(local)
    job(["pipelines/load_siat.py"], local)


@app.command()
def dev(port: int = typer.Option(5174, help="frontend dev-server port")) -> None:
    """Run everything locally without Docker: database + API (:8000) + frontend. Ctrl+C stops the app."""
    db_start()
    migrate(True)
    npm = shutil.which("npm")
    if npm is None:
        typer.secho("npm not found - install Node.js 20+ to run the frontend.", fg=typer.colors.RED)
        raise typer.Exit(1)
    if not (ROOT / "frontend" / "node_modules").exists():
        subprocess.check_call([npm, "install", "--no-audit", "--no-fund"], cwd=ROOT / "frontend")
    procs = [
        subprocess.Popen(
            [
                PY,
                "-m",
                "uvicorn",
                "app.main:app",
                "--app-dir",
                "backend",
                "--reload",
                "--reload-dir",
                "backend",
                "--port",
                "8000",
            ],
            cwd=ROOT,
        ),
        subprocess.Popen([npm, "run", "dev", "--", "--port", str(port), "--strictPort"], cwd=ROOT / "frontend"),
    ]
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT), str(ROOT / "backend")])}
    extras = []
    try:  # optional services: they must never stop the app from starting
        procs.append(subprocess.Popen([PY, "-m", "mcp_server.server"], cwd=ROOT, env=env))
        extras.append("  MCP:    http://localhost:8100/mcp")
    except OSError:
        pass
    mlflow_exe = Path(PY).with_name("mlflow.exe" if sys.platform == "win32" else "mlflow")
    if mlflow_exe.exists():
        store = "sqlite:///" + (ROOT / ".tools" / "mlflow.db").as_posix()
        procs.append(
            subprocess.Popen(
                [str(mlflow_exe), "ui", "--backend-store-uri", store, "--port", "5000", "--host", "127.0.0.1"],
                cwd=ROOT,
                env={**env, "MLFLOW_DISABLE_AGENT_HINT": "1"},
            )
        )
        extras.append("  MLflow: http://localhost:5000")
    typer.secho(
        f"\n  App:    http://localhost:{port}\n  API:    http://localhost:8000/docs\n"
        + "\n".join(extras)
        + "\n  Ctrl+C to stop (the database keeps running; `python manage.py db-stop` stops it).\n",
        fg=typer.colors.GREEN,
    )
    try:
        while all(p.poll() is None for p in procs[:2]):
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            if p.poll() is None:
                p.terminate()
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()


@app.command()
def seed(local: bool = typer.Option(False, help="run on the host instead of the worker container")) -> None:
    """Reference geography (Phase 2) + RAG index (Phase 8)."""
    job(["pipelines/load_reference.py"], local)
    job(["-m", "rag.ingest"], local)


@app.command()
def features(local: bool = typer.Option(False, help="run on the host instead of the worker container")) -> None:
    """Compute features from official observations (Phase 3)."""
    job(["-m", "ml.features.pipeline"], local)


@app.command()
def train(local: bool = typer.Option(False, help="run on the host instead of the worker container")) -> None:
    """Backtest + train forecasting models, write forecasts, log to MLflow (Phase 5)."""
    job(["-m", "ml.forecasting.train"], local)


@app.command("eval")
def evaluate(local: bool = typer.Option(False, help="run on the host instead of the worker container")) -> None:
    """Recommendation, forecast, agent and RAG evaluation -> docs/evaluation_report.md (Phase 11)."""
    job(["-m", "ml.evaluation.run_all"], local)


@app.command()
def monitor(local: bool = typer.Option(False, help="run on the host instead of the worker container")) -> None:
    """Data quality, feature drift, realised error, recommendation stability (Phase 10)."""
    job(["-m", "monitoring.drift"], local)


@app.command()
def demo(
    download: bool = typer.Option(False, help="refresh datasets from SIAT (default: use cached raw files)"),
    docker: bool = typer.Option(False, help="start the Docker stack first"),
) -> None:
    """One command: database -> ingest -> seed -> features -> train -> monitor -> eval, then print URLs."""
    local = not (docker and docker_available())
    if not local:
        up(build=True)
    elif PG_BIN.exists():  # portable PostgreSQL on this machine
        if not (PG_DATA / "PG_VERSION").exists():
            db_init()
        db_start()
    # otherwise (e.g. inside the Docker worker) DATABASE_URL points at a running database
    raw = ROOT / "data" / "raw" / "siat"
    ingest(local=local, download=download or not any(raw.glob("*.json")))
    seed(local=local)
    features(local=local)
    train(local=local)
    monitor(local=local)
    evaluate(local=local)
    typer.secho(
        "\n  Demo data ready.\n"
        + ("  Start the app:  python manage.py dev\n" if local else "")
        + "  App:     http://localhost:"
        + ("5174" if local else "8080")
        + "\n  API:     http://localhost:8000/docs\n  MLflow:  http://localhost:5000\n  MCP:     http://localhost:8100/mcp\n",
        fg=typer.colors.GREEN,
    )


# --- scheduled data refresh --------------------------------------------------------------

TASK_NAME = "Uzbekistan Smart BI - data refresh"


@app.command()
def refresh(
    force: bool = typer.Option(False, help="recompute features/forecasts even if SIAT has no new data"),
    trigger: str = typer.Option("manual", help="manual | schedule (recorded in pipeline_runs)"),
) -> None:
    """Download new SIAT data and rebuild what depends on it (features, forecasts, RAG, monitoring)."""
    if PG_BIN.exists():
        db_start()  # scheduled runs may start before the app
    job(["pipelines/refresh.py", "--trigger", trigger] + (["--force"] if force else []), local=True)


@app.command()
def scheduler() -> None:
    """Run forever, refreshing every REFRESH_EVERY_DAYS at REFRESH_AT (for servers / the Docker service)."""
    job(["pipelines/scheduler.py"], local=True)


def _settings_value(key: str, default: str) -> str:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith(f"{key}="):
                return line.split("=", 1)[1].strip() or default
    return os.environ.get(key, default)


@app.command()
def schedule(
    every_days: int = typer.Option(None, help="days between refreshes (default REFRESH_EVERY_DAYS from .env, 7)"),
    at: str = typer.Option(None, help="local time HH:MM (default REFRESH_AT from .env, 03:00)"),
    remove: bool = typer.Option(False, "--remove", help="delete the scheduled task"),
    status: bool = typer.Option(False, "--status", help="show the scheduled task"),
) -> None:
    """Windows: register `manage.py refresh` in Task Scheduler for the current user (no admin needed)."""
    if sys.platform != "win32":
        typer.secho(
            "On Linux/macOS use the Docker `scheduler` service or cron, e.g.\n"
            f"  0 3 */3 * *  cd {ROOT} && {PY} manage.py refresh --trigger schedule",
            fg=typer.colors.YELLOW,
        )
        raise typer.Exit(0)
    ps = ["powershell", "-NoProfile", "-NonInteractive", "-Command"]
    if remove:
        run([*ps, f"Unregister-ScheduledTask -TaskName '{TASK_NAME}' -Confirm:$false"], check=False)
        return
    if status:
        run(
            [
                *ps,
                f"$t = Get-ScheduledTask -TaskName '{TASK_NAME}' -ErrorAction SilentlyContinue; "
                "if (-not $t) { 'No scheduled refresh task.' } else { "
                f"$i = Get-ScheduledTaskInfo -TaskName '{TASK_NAME}'; "
                "'State: ' + $t.State; "
                # 267011 = SCHED_S_TASK_HAS_NOT_RUN
                "if ($i.LastTaskResult -eq 267011) { 'Last run: never' } "
                "else { 'Last run: ' + $i.LastRunTime + ' (result ' + $i.LastTaskResult + ')' }; "
                "'Next run: ' + $i.NextRunTime }",
            ],
            check=False,
        )
        return
    days = every_days or int(_settings_value("REFRESH_EVERY_DAYS", "7"))
    time_at = at or _settings_value("REFRESH_AT", "03:00")
    # StartWhenAvailable: if the computer was off at the scheduled time, run as soon as it is on again.
    script = (
        f"$a = New-ScheduledTaskAction -Execute '{PY}' -Argument 'manage.py refresh --trigger schedule' "
        f"-WorkingDirectory '{ROOT}'; "
        f"$t = New-ScheduledTaskTrigger -Daily -DaysInterval {days} -At '{time_at}'; "
        "$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries "
        "-AllowStartIfOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 3) -MultipleInstances IgnoreNew; "
        f"Register-ScheduledTask -TaskName '{TASK_NAME}' -Action $a -Trigger $t -Settings $s "
        "-Description 'Downloads new SIAT data and rebuilds features, forecasts and the RAG index' -Force | Out-Null; "
        f"(Get-ScheduledTaskInfo -TaskName '{TASK_NAME}').NextRunTime"
    )
    run([*ps, script])
    typer.secho(
        f"Scheduled: refresh every {days} day(s) at {time_at} (task '{TASK_NAME}'). "
        "Runs while you are logged in; a missed run starts when the computer is back on.\n"
        "Check: python manage.py schedule --status   Remove: python manage.py schedule --remove",
        fg=typer.colors.GREEN,
    )


@app.command()
def backup() -> None:
    """pg_dump of the sbi database into ./backups (custom format)."""
    out = ROOT / "backups"
    out.mkdir(exist_ok=True)
    target = out / f"sbi-{time.strftime('%Y%m%d-%H%M%S')}.dump"
    run([pg("pg_dump"), "-h", "localhost", "-p", PG_PORT, "-U", PG_USER, "-d", PG_DB, "-Fc", "-f", str(target)])
    typer.secho(f"Backup written: {target.relative_to(ROOT)}", fg=typer.colors.GREEN)


@app.command()
def restore(file: Path = typer.Argument(None, help="dump to restore (default: newest in ./backups)")) -> None:
    """Restore a pg_dump made by `backup` (replaces existing objects)."""
    dumps = sorted((ROOT / "backups").glob("*.dump"))
    target = file or (dumps[-1] if dumps else None)
    if target is None or not Path(target).exists():
        typer.secho("No backup found in ./backups", fg=typer.colors.RED)
        raise typer.Exit(1)
    run(
        [pg("pg_restore"), "-h", "localhost", "-p", PG_PORT, "-U", PG_USER, "-d", PG_DB, "--clean", "--if-exists"]
        + ["--no-owner", str(target)]
    )
    typer.secho(f"Restored {target}", fg=typer.colors.GREEN)


@app.command()
def selftest(local: bool = typer.Option(True, help="run on the host (default) or in the worker")) -> None:
    """Offline parser test of pipelines/siat_ingest.py."""
    job(["pipelines/siat_ingest.py", "selftest"], local)


# --- quality -----------------------------------------------------------------


@app.command()
def test(args: list[str] = typer.Argument(None)) -> None:
    """Run pytest on the host (.venv)."""
    run([PY, "-m", "pytest", *(args or [])])


@app.command()
def lint(fix: bool = typer.Option(False, help="apply fixes and format")) -> None:
    """ruff check (+ ruff format with --fix)."""
    if fix:
        run([PY, "-m", "ruff", "check", "--fix", "."])
        run([PY, "-m", "ruff", "format", "."])
    else:
        run([PY, "-m", "ruff", "check", "."])
        run([PY, "-m", "ruff", "format", "--check", "."])


if __name__ == "__main__":
    app()
