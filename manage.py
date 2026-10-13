#!/usr/bin/env python3
"""Cross-platform task runner (works on Windows PowerShell without make).

    python manage.py up | down | logs | ps
    python manage.py ingest | seed | features | train | eval | monitor | demo
    python manage.py test | lint | selftest

Jobs that need the database run inside the worker container
(`docker compose run --rm worker ...`). Pass --local to run them on the host instead.
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


def job(args: list[str], local: bool) -> None:
    """Run a Python job either in the worker container or on the host."""
    if local:
        run([PY, *args])
    else:
        run(compose("run", "--rm", "worker", "python", *args))


def not_yet(phase: int) -> None:
    typer.secho(f"Not implemented yet — arrives in Phase {phase} (see PLAN.md).", fg=typer.colors.YELLOW)
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
            "pgvector is not available locally — RAG will use BM25 only (allowed by CLAUDE.md rule 10).",
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
        typer.secho(f"PostgreSQL failed to start — see {PG_LOG}", fg=typer.colors.RED)
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
        typer.secho("npm not found — install Node.js 20+ to run the frontend.", fg=typer.colors.RED)
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
    typer.secho(
        f"\n  App:  http://localhost:{port}\n  API:  http://localhost:8000/docs\n  Ctrl+C to stop "
        "(the database keeps running; `python manage.py db-stop` stops it).\n",
        fg=typer.colors.GREEN,
    )
    try:
        while all(p.poll() is None for p in procs):
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
def seed(local: bool = typer.Option(False)) -> None:
    """Reference data, geo boundaries, synthetic gap-fill, RAG index (Phases 1, 2, 8)."""
    not_yet(2)


@app.command()
def features(local: bool = typer.Option(False)) -> None:
    """Compute features (Phase 3)."""
    not_yet(3)


@app.command()
def train(local: bool = typer.Option(False)) -> None:
    """Train forecasting models → MLflow (Phase 5)."""
    not_yet(5)


@app.command("eval")
def evaluate(local: bool = typer.Option(False)) -> None:
    """Recommendation, forecast, agent and RAG evaluation (Phase 11)."""
    not_yet(11)


@app.command()
def monitor(local: bool = typer.Option(False)) -> None:
    """Drift and data-quality metrics (Phase 10)."""
    not_yet(10)


@app.command()
def demo() -> None:
    """up + ingest + seed + features + train in one go (Phase 12)."""
    not_yet(12)


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
