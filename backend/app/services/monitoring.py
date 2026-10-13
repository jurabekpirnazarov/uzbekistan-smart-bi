"""Monitoring data for the frontend page and the /metrics batch gauges (PLAN.md Phase 10)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.db.models import (
    AgentRun,
    AgentToolCall,
    DataSource,
    Feedback,
    IngestionRun,
    ModelMetric,
    MonitorMetric,
    Observation,
    PipelineRun,
    Prediction,
    Recommendation,
)
from app.db.session import get_sessionmaker


def _latest_snapshot(db: Session) -> list[MonitorMetric]:
    last = db.scalar(select(func.max(MonitorMetric.created_at)))
    if last is None:
        return []
    return list(db.scalars(select(MonitorMetric).where(MonitorMetric.created_at == last)).all())


def latest_batch_metrics() -> dict[str, list[dict]]:
    """For the Prometheus collector: metric name -> [{labels, value}] from the latest monitor run."""
    with get_sessionmaker()() as db:
        out: dict[str, list[dict]] = {}
        for m in _latest_snapshot(db):
            if m.value is not None:
                out.setdefault(m.name, []).append({"labels": m.labels or {}, "value": m.value})
        last_ok = db.scalar(
            select(func.max(PipelineRun.finished_at)).where(PipelineRun.status.in_(["ok", "no_change"]))
        )
        if last_ok is not None:
            out["pipeline_last_success_timestamp"] = [{"labels": {}, "value": last_ok.timestamp()}]
        for status, n in db.execute(select(PipelineRun.status, func.count()).group_by(PipelineRun.status)).all():
            out.setdefault("pipeline_runs_total", []).append({"labels": {"status": status}, "value": float(n)})
        return out


def _next_slot(last: datetime, every_days: int, at: str) -> datetime:
    """Same rule as pipelines/scheduler.py: `every_days` after the last success, at the HH:MM slot (local time)."""
    hh, mm = (int(x) for x in at.split(":"))
    return (last.astimezone() + timedelta(days=every_days)).replace(hour=hh, minute=mm, second=0, microsecond=0)


def pipeline_status(db: Session) -> dict:
    """Scheduled refresh: recent runs and when the next one is due."""
    from app.core.config import get_settings

    s = get_settings()
    runs = db.scalars(select(PipelineRun).order_by(PipelineRun.started_at.desc()).limit(10)).all()
    last_ok = next((r for r in runs if r.status in ("ok", "no_change") and r.finished_at), None)
    return {
        "every_days": s.refresh_every_days,
        "at": s.refresh_at,
        "next_due_after": _next_slot(last_ok.finished_at, s.refresh_every_days, s.refresh_at) if last_ok else None,
        "runs": [
            {
                "started_at": r.started_at,
                "finished_at": r.finished_at,
                "trigger": r.trigger,
                "status": r.status,
                "datasets_changed": r.datasets_changed or [],
                "datasets_added": r.datasets_added or [],
                "steps": r.steps or [],
                "error": r.error,
            }
            for r in runs
        ],
    }


def data_health(db: Session) -> dict:
    snap = _latest_snapshot(db)
    src = db.execute(select(DataSource.name, DataSource.url, DataSource.retrieved_at)).all()
    runs = db.scalars(select(IngestionRun).order_by(IngestionRun.started_at.desc()).limit(10)).all()
    last = db.scalar(select(func.max(Observation.retrieved_at)))
    return {
        "observations": db.scalar(select(func.count(Observation.id))),
        "last_retrieved_at": last,
        "age_days": (datetime.now(UTC) - last).days if last else None,
        "sources": [{"name": n, "url": u, "retrieved_at": r} for n, u, r in src],
        "ingestion_runs": [
            {
                "started_at": r.started_at,
                "status": r.status,
                "datasets_ok": r.datasets_ok,
                "rows_loaded": r.rows_loaded,
                "rows_rejected": r.rows_rejected,
            }
            for r in runs
        ],
        "quality_checks": [
            {"check": m.labels.get("check"), "passed": m.value == 1}
            for m in snap
            if m.name == "data_quality_check_passed"
        ],
        "missing_ratio": sorted(
            [
                {"indicator": m.labels.get("indicator"), "ratio": m.value}
                for m in snap
                if m.name == "data_missing_ratio"
            ],
            key=lambda x: -(x["ratio"] or 0),
        ),
        "snapshot_at": snap[0].created_at if snap else None,
        "pipeline": pipeline_status(db),
    }


def model_health(db: Session) -> dict:
    run = db.scalar(select(ModelMetric.run_id).where(ModelMetric.kind == "forecast").order_by(ModelMetric.id.desc()))
    rows = db.execute(
        select(
            ModelMetric.indicator_code,
            ModelMetric.level,
            ModelMetric.model,
            ModelMetric.horizon,
            ModelMetric.metric,
            ModelMetric.value,
            ModelMetric.is_selected,
        ).where(ModelMetric.run_id == run, ModelMetric.metric.in_(["smape", "improvement_vs_naive_pct"]))
    ).all()
    board: dict[tuple, dict] = {}
    for ind, lv, model, h, metric, value, sel in rows:
        r = board.setdefault((ind, lv, model), {"indicator": ind, "level": lv, "model": model, "selected": sel})
        r[f"{metric}_h{h}"] = value
    snap = _latest_snapshot(db)
    return {
        "run_id": run,
        "trained_at": db.scalar(select(func.max(Prediction.created_at))),
        "leaderboard": sorted(board.values(), key=lambda r: (r["indicator"], r["level"], r.get("smape_h1") or 1e9)),
        "drift": [
            {
                "feature": m.labels.get("feature"),
                "years": m.labels.get("years"),
                "psi": m.value,
                "alert": (m.value or 0) > 0.2,
            }
            for m in snap
            if m.name == "feature_drift_psi"
        ],
        "realised_error": [
            {"indicator": m.labels.get("indicator"), "model": m.labels.get("model"), "mape": m.value}
            for m in snap
            if m.name == "prediction_realized_error"
        ],
    }


def reco_health(db: Session) -> dict:
    by_type = db.execute(
        select(Recommendation.business_type, func.count()).group_by(Recommendation.business_type)
    ).all()
    counts: dict[str, int] = {}
    for (top,) in db.execute(select(Recommendation.top).where(Recommendation.top.is_not(None))).all():
        for s in (top or [])[:5]:
            counts[s] = counts.get(s, 0) + 1
    snap = _latest_snapshot(db)
    fb = dict(db.execute(select(Feedback.rating, func.count()).group_by(Feedback.rating)).all())
    return {
        "requests": [{"business_type": b, "count": n} for b, n in sorted(by_type, key=lambda x: -x[1])],
        "most_recommended": sorted(counts.items(), key=lambda x: -x[1])[:10],
        "stability": [
            {"business_type": m.labels.get("business_type"), "jaccard": m.value}
            for m in snap
            if m.name == "recommendation_stability_jaccard"
        ],
        "feedback": {"up": fb.get(1, 0), "down": fb.get(-1, 0)},
    }


def agent_health(db: Session, days: int = 7) -> dict:
    since = datetime.now(UTC) - timedelta(days=days)
    runs = db.scalars(select(AgentRun).where(AgentRun.created_at >= since).order_by(AgentRun.created_at.desc())).all()
    lat = np.array([r.latency_ms for r in runs]) if runs else np.array([])
    tools = db.execute(
        select(AgentToolCall.name, func.count(), func.sum(case((AgentToolCall.ok.is_(False), 1), else_=0)))
        .join(AgentRun, AgentRun.id == AgentToolCall.run_id)
        .where(AgentRun.created_at >= since)
        .group_by(AgentToolCall.name)
    ).all()
    return {
        "window_days": days,
        "runs": len(runs),
        "errors": sum(r.status == "error" for r in runs),
        "fallback_runs": sum(r.mode == "fallback" for r in runs),
        "p50_ms": float(np.percentile(lat, 50)) if len(lat) else None,
        "p95_ms": float(np.percentile(lat, 95)) if len(lat) else None,
        "tokens": int(sum(r.tokens_in + r.tokens_out for r in runs)),
        "cost_usd": round(float(sum(r.cost_usd for r in runs)), 4),
        "verification_failures": int(sum(r.verification_failures for r in runs)),
        "tools": [{"tool": n, "calls": c, "failures": int(f or 0)} for n, c, f in sorted(tools, key=lambda x: -x[1])],
        "recent": [
            {
                "created_at": r.created_at,
                "question": r.question[:160],
                "lang": r.lang,
                "intent": r.intent,
                "mode": r.mode,
                "status": r.status,
                "latency_ms": r.latency_ms,
                "tool_count": r.tool_count,
                "verification_failures": r.verification_failures,
            }
            for r in runs[:20]
        ],
    }
