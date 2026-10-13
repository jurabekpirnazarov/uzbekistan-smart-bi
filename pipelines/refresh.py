"""Scheduled data refresh: download → load → (if data changed) features → train → RAG index → monitor.

Usage:  python manage.py refresh [--force]       (scheduled by `manage.py schedule` or the Docker scheduler)

- SIAT datasets are re-downloaded only when the catalog says they were updated (siat_ingest.py caching);
  content changes are detected by comparing the sha256 of each raw file before and after the download.
- Loading is idempotent (upsert), so it always runs; the expensive steps run only when something changed
  (or with --force). Monitoring always runs, so data freshness and quality are re-checked every time.
- Every run is recorded in `pipeline_runs` (status, changed datasets, per-step timings, error) and logged to
  logs/refresh-YYYYMMDD.log. A lock file prevents two runs at the same time.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.db.models import PipelineRun  # noqa: E402
from app.db.session import get_sessionmaker  # noqa: E402

RAW = ROOT / "data" / "raw" / "siat" / "datasets"
LOCK = ROOT / "logs" / "refresh.lock"
STALE_LOCK_HOURS = 6


def mapped_ids() -> list[int]:
    m = yaml.safe_load((ROOT / "data" / "reference" / "indicator_map.yaml").read_text(encoding="utf-8"))
    ids = [s["siat_dataset_id"] for s in m["indicators"].values()]
    ids += [r["siat_dataset_id"] for r in (m.get("reference") or {}).values()]
    return sorted(set(ids))


def fingerprints(ids: list[int]) -> dict[int, str | None]:
    out: dict[int, str | None] = {}
    for i in ids:
        meta = RAW / f"{i}.meta.json"
        out[i] = json.loads(meta.read_text(encoding="utf-8")).get("sha256") if meta.exists() else None
    return out


class Runner:
    """Runs steps as subprocesses, tees their output into the log file and records timings."""

    def __init__(self, log_path: Path) -> None:
        self.log = log_path.open("a", encoding="utf-8")
        self.steps: list[dict] = []
        self.env = {
            **os.environ,
            "PYTHONPATH": os.pathsep.join([str(ROOT), str(ROOT / "backend")]),
            "PYTHONIOENCODING": "utf-8",
            "MLFLOW_DISABLE_AGENT_HINT": "1",
        }

    def say(self, msg: str) -> None:
        line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
        print(line, flush=True)
        self.log.write(line + "\n")
        self.log.flush()

    def step(self, name: str, args: list[str]) -> None:
        self.say(f"▶ {name}: {' '.join(args)}")
        t0 = time.time()
        proc = subprocess.run(
            [sys.executable, *args],
            cwd=ROOT,
            env=self.env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        self.log.write(proc.stdout + proc.stderr)
        secs = round(time.time() - t0, 1)
        ok = proc.returncode == 0
        self.steps.append({"name": name, "status": "ok" if ok else "failed", "seconds": secs})
        self.say(f"{'✓' if ok else '✕'} {name} ({secs}s)")
        if not ok:
            tail = (proc.stderr or proc.stdout).strip().splitlines()[-5:]
            raise RuntimeError(f"step '{name}' failed: " + " | ".join(tail))

    def skip(self, name: str, why: str) -> None:
        self.steps.append({"name": name, "status": "skipped", "seconds": 0, "reason": why})
        self.say(f"– {name} skipped ({why})")


def acquire_lock() -> bool:
    LOCK.parent.mkdir(exist_ok=True)
    if LOCK.exists() and time.time() - LOCK.stat().st_mtime < STALE_LOCK_HOURS * 3600:
        return False
    LOCK.write_text(str(os.getpid()), encoding="utf-8")
    return True


def run(force: bool = False, trigger: str = "manual") -> int:
    if not acquire_lock():
        print(f"Another refresh is running (lock {LOCK}); exiting.")
        return 0
    logs = ROOT / "logs"
    r = Runner(logs / f"refresh-{datetime.now():%Y%m%d}.log")
    ids = mapped_ids()
    Session = get_sessionmaker()
    with Session() as db:
        row = PipelineRun(
            trigger=trigger, started_at=datetime.now(UTC), status="running", datasets_checked=len(ids), steps=[]
        )
        db.add(row)
        db.commit()
        run_id = row.id
    status, error, changed = "failed", None, []
    try:
        before = fingerprints(ids)
        r.step("download", ["pipelines/siat_ingest.py", "fetch", "--ids", *map(str, ids)])
        after = fingerprints(ids)
        changed = [i for i in ids if after.get(i) and after.get(i) != before.get(i)]
        r.say(f"datasets with new content: {changed or 'none'}")
        r.step("migrate", ["-m", "alembic", "-c", "backend/alembic.ini", "upgrade", "head"])
        r.step("load", ["pipelines/load_siat.py"])
        if changed or force:
            r.step("features", ["-m", "ml.features.pipeline"])
            r.step("train", ["-m", "ml.forecasting.train"])
            r.step("rag_index", ["-m", "rag.ingest"])
        else:
            for s in ("features", "train", "rag_index"):
                r.skip(s, "no new data")
        r.step("monitor", ["-m", "monitoring.drift"])
        status = "ok" if (changed or force) else "no_change"
    except Exception as e:  # recorded, then re-signalled through the exit code
        error = str(e)[:2000]
        r.say(f"FAILED: {error}")
    finally:
        with Session() as db:
            row = db.get(PipelineRun, run_id)
            if row is not None:
                row.finished_at = datetime.now(UTC)
                row.status = status
                row.datasets_changed = changed
                row.steps = r.steps
                row.error = error
                db.commit()
        LOCK.unlink(missing_ok=True)
        r.say(f"refresh finished: {status}")
    return 0 if status != "failed" else 1


def main() -> None:
    p = argparse.ArgumentParser(description="Download new SIAT data and rebuild everything that depends on it")
    p.add_argument("--force", action="store_true", help="recompute features/forecasts even without new data")
    p.add_argument("--trigger", default="manual", choices=["manual", "schedule"])
    a = p.parse_args()
    sys.exit(run(a.force, a.trigger))


if __name__ == "__main__":
    main()
