"""Long-running scheduler for servers / Docker: runs pipelines/refresh.py every N days at a fixed time.

Usage:  python manage.py scheduler            (the `scheduler` service in docker-compose.yml)
Config: REFRESH_EVERY_DAYS (default 3) and REFRESH_AT (local time HH:MM, default 03:00) in .env.

The next run is computed from the last successful run in `pipeline_runs`, so restarting the container
does not trigger an extra download; a missed run (machine was off) starts right away.
On Windows without Docker use `python manage.py schedule` (Windows Task Scheduler) instead.
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import select  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.db.models import PipelineRun  # noqa: E402
from app.db.session import get_sessionmaker  # noqa: E402

CHECK_EVERY_S = 300


def next_run(last_success: datetime | None, every_days: int, at: str, now: datetime) -> datetime:
    """First HH:MM slot that is at least `every_days` after the last success (now if overdue / never ran)."""
    hh, mm = (int(x) for x in at.split(":"))
    if last_success is None:
        return now
    due = (last_success + timedelta(days=every_days)).replace(hour=hh, minute=mm, second=0, microsecond=0)
    return now if due <= now else due


def last_success() -> datetime | None:
    with get_sessionmaker()() as db:
        ts = db.scalar(
            select(PipelineRun.finished_at)
            .where(PipelineRun.status.in_(["ok", "no_change"]))
            .order_by(PipelineRun.finished_at.desc())
            .limit(1)
        )
    return ts.astimezone().replace(tzinfo=None) if ts else None


def main() -> None:
    from pipelines.refresh import run

    s = get_settings()
    print(f"scheduler: refresh every {s.refresh_every_days} day(s) at {s.refresh_at}", flush=True)
    while True:
        try:
            due = next_run(last_success(), s.refresh_every_days, s.refresh_at, datetime.now())
        except Exception as e:  # database not up yet
            print(f"scheduler: waiting for the database ({type(e).__name__})", flush=True)
            time.sleep(30)
            continue
        if datetime.now() >= due:
            run(trigger="schedule")
            time.sleep(60)
            continue
        wait = min(CHECK_EVERY_S, (due - datetime.now()).total_seconds())
        time.sleep(max(wait, 1))


if __name__ == "__main__":
    main()
