"""Every Prometheus metric in one place (PLAN.md Phase 10).

Live metrics are counters/histograms updated in-process. Batch-job metrics (ingestion, data quality,
backtests, drift, stability) are written to the database by the jobs and exported here as gauges at
scrape time by DbGaugeCollector — no Pushgateway needed.
"""

from __future__ import annotations

from collections.abc import Iterator

from prometheus_client import REGISTRY, Counter, Histogram
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector

LATENCY_BUCKETS = (0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 40, 80)

# --- agent ---------------------------------------------------------------------------------
AGENT_REQUESTS = Counter("agent_requests_total", "Chat agent requests", ["intent", "status", "lang"])
AGENT_LATENCY = Histogram("agent_latency_seconds", "Chat agent end-to-end latency", ["mode"], buckets=LATENCY_BUCKETS)
AGENT_TOOL_CALLS = Counter("agent_tool_calls_total", "Agent tool calls", ["tool", "status"])
AGENT_TOOL_LATENCY = Histogram("agent_tool_latency_seconds", "Agent tool latency", ["tool"], buckets=LATENCY_BUCKETS)
AGENT_TOKENS = Counter("agent_tokens_total", "LLM tokens", ["kind", "model"])
AGENT_COST = Counter("agent_cost_usd_total", "Estimated LLM cost in USD", ["model"])
AGENT_VERIFICATION_FAILURES = Counter(
    "agent_verification_failures_total", "Numbers in answers that no tool result supports"
)

# --- RAG -----------------------------------------------------------------------------------
RAG_TOP_SCORE = Histogram(
    "rag_retrieval_top_score", "Top fused retrieval score", buckets=(0.005, 0.01, 0.02, 0.03, 0.05, 0.1, 0.5, 1)
)
RAG_EMPTY = Counter("rag_empty_results_total", "Retrievals that returned nothing")

# --- MCP -----------------------------------------------------------------------------------
MCP_TOOL_CALLS = Counter("mcp_tool_calls_total", "MCP tool calls", ["tool", "status"])
MCP_TOOL_LATENCY = Histogram("mcp_tool_latency_seconds", "MCP tool latency", ["tool"], buckets=LATENCY_BUCKETS)

# --- recommendations -----------------------------------------------------------------------
RECO_REQUESTS = Counter("recommendation_requests_total", "Recommendation requests", ["business_type"])
RECO_SCORE = Histogram(
    "recommendation_score", "Returned opportunity scores", ["business_type"], buckets=tuple(range(0, 101, 10))
)
RECO_LOW_COVERAGE = Counter(
    "recommendation_low_coverage_total", "Entities excluded for insufficient data", ["business_type"]
)

# --- feedback ------------------------------------------------------------------------------
USER_FEEDBACK = Counter("user_feedback_total", "User feedback", ["rating"])

# Batch gauges exported from the database: metric name -> (help, label names).
DB_GAUGES: dict[str, tuple[str, list[str]]] = {
    "ingestion_runs_total": ("Ingestion runs by status (from ingestion_runs)", ["source", "status"]),
    "ingestion_rows_total": ("Rows loaded/rejected by the last ingestion", ["source", "result"]),
    "data_last_update_timestamp": ("Unix time of the latest retrieved observation", ["source"]),
    "pipeline_last_success_timestamp": ("Unix time of the last successful scheduled/manual refresh", []),
    "pipeline_runs_total": ("Refresh pipeline runs by status", ["status"]),
    "data_quality_check_passed": ("1 if a data-quality check passed", ["check"]),
    "data_missing_ratio": ("Share of expected district-year cells that are missing", ["indicator"]),
    "model_backtest_smape": ("Backtest sMAPE of the selected model", ["indicator", "level", "model"]),
    "feature_drift_psi": ("PSI between the previous and the latest year", ["feature", "years"]),
    "prediction_realized_error": ("Realised error of last year's forecast (MAPE)", ["indicator", "model"]),
    "recommendation_stability_jaccard": ("Top-5 Jaccard between consecutive runs", ["business_type"]),
    "recommendation_rank_width": ("Mean p10-p90 rank width of the top 5", ["business_type"]),
}


class DbGaugeCollector(Collector):
    """Reads the latest batch metrics at scrape time. Never raises (a scrape must not fail)."""

    def collect(self) -> Iterator[GaugeMetricFamily]:
        try:
            from app.services.monitoring import latest_batch_metrics

            rows = latest_batch_metrics()
        except Exception:  # database down → just no batch gauges
            return
        for name, (doc, labels) in DB_GAUGES.items():
            fam = GaugeMetricFamily(name, doc, labels=labels)
            for r in rows.get(name, []):
                fam.add_metric([str(r["labels"].get(lbl, "")) for lbl in labels], float(r["value"]))
            yield fam


_registered = False


def register_db_collector() -> None:
    global _registered
    if not _registered:
        REGISTRY.register(DbGaugeCollector())
        _registered = True
