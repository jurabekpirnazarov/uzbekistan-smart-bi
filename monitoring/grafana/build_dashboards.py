"""Generate the 5 provisioned Grafana dashboards (PLAN.md Phase 10) as JSON.

Usage:  python monitoring/grafana/build_dashboards.py   (writes monitoring/grafana/dashboards/*.json)
Dashboards are code: edit the panel lists below, not the JSON.
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).with_name("dashboards")
PROM = {"type": "prometheus", "uid": "prometheus"}
PG = {"type": "grafana-postgresql-datasource", "uid": "postgres"}


def panel(
    title: str,
    expr: str | list[str],
    kind: str = "timeseries",
    unit: str = "short",
    w: int = 12,
    h: int = 8,
    legend: str = "",
    thresholds: list[tuple[float, str]] | None = None,
) -> dict:
    exprs = expr if isinstance(expr, list) else [expr]
    p = {
        "type": kind,
        "title": title,
        "datasource": PROM,
        "gridPos": {"w": w, "h": h},
        "targets": [
            {
                "datasource": PROM,
                "expr": e,
                "refId": chr(65 + i),
                "legendFormat": legend,
                "instant": kind in ("stat", "table", "bargauge"),
            }
            for i, e in enumerate(exprs)
        ],
        "fieldConfig": {"defaults": {"unit": unit}, "overrides": []},
        "options": {},
    }
    if thresholds:
        p["fieldConfig"]["defaults"]["thresholds"] = {
            "mode": "absolute",
            "steps": [{"color": c, "value": v} for v, c in thresholds],
        }
        p["fieldConfig"]["defaults"]["color"] = {"mode": "thresholds"}
    if kind == "table":
        p["options"] = {"showHeader": True}
        p["transformations"] = [{"id": "labelsToFields", "options": {}}]
    return p


def sql_panel(title: str, sql: str, w: int = 24, h: int = 9) -> dict:
    return {
        "type": "table",
        "title": title,
        "datasource": PG,
        "gridPos": {"w": w, "h": h},
        "targets": [
            {"datasource": PG, "refId": "A", "format": "table", "rawQuery": True, "rawSql": sql, "editorMode": "code"}
        ],
    }


def dashboard(uid: str, title: str, panels: list[dict]) -> dict:
    x = y = row_h = 0
    for i, p in enumerate(panels, 1):
        gp = p["gridPos"]
        if x + gp["w"] > 24:
            x, y = 0, y + row_h
            row_h = 0
        gp.update({"x": x, "y": y})
        x += gp["w"]
        row_h = max(row_h, gp["h"])
        p["id"] = i
    return {
        "uid": uid,
        "title": title,
        "tags": ["smart-bi"],
        "timezone": "browser",
        "schemaVersion": 39,
        "time": {"from": "now-24h", "to": "now"},
        "refresh": "30s",
        "panels": panels,
    }


GREEN, AMBER, RED = "green", "orange", "red"

DASHBOARDS = {
    "data-health": dashboard(
        "sbi-data",
        "Smart BI · Data Health",
        [
            panel(
                "Data age (days)",
                "(time() - max(data_last_update_timestamp)) / 86400",
                "stat",
                "d",
                6,
                5,
                thresholds=[(0, GREEN), (30, AMBER), (45, RED)],
            ),
            panel(
                "Quality checks passing",
                "sum(data_quality_check_passed) / count(data_quality_check_passed)",
                "stat",
                "percentunit",
                6,
                5,
                thresholds=[(0, RED), (1, GREEN)],
            ),
            panel("Rows loaded (last run)", 'sum(ingestion_rows_total{result="loaded"})', "stat", "short", 6, 5),
            panel(
                "Rows rejected (last run)",
                'sum(ingestion_rows_total{result="rejected"})',
                "stat",
                "short",
                6,
                5,
                thresholds=[(0, GREEN), (1, RED)],
            ),
            panel("Quality checks", "data_quality_check_passed", "table", w=12, h=9),
            panel(
                "Missing district-year ratio by indicator",
                "sort_desc(data_missing_ratio)",
                "bargauge",
                "percentunit",
                12,
                9,
                "{{indicator}}",
            ),
            panel("Ingestion runs by status", "ingestion_runs_total", "table", w=24, h=6),
        ],
    ),
    "ml-models": dashboard(
        "sbi-models",
        "Smart BI · ML Models",
        [
            panel(
                "Backtest sMAPE of selected models (%)",
                "sort_desc(model_backtest_smape)",
                "bargauge",
                "percent",
                12,
                10,
                "{{indicator}} · {{level}} · {{model}}",
                thresholds=[(0, GREEN), (15, AMBER), (30, RED)],
            ),
            panel(
                "Realised error of last year's forecast (MAPE %)",
                "prediction_realized_error",
                "bargauge",
                "percent",
                12,
                10,
                "{{indicator}} ({{model}})",
            ),
            panel(
                "Feature drift (PSI, previous vs latest year)",
                "sort_desc(feature_drift_psi)",
                "bargauge",
                "short",
                24,
                10,
                "{{feature}} {{years}}",
                thresholds=[(0, GREEN), (0.1, AMBER), (0.2, RED)],
            ),
        ],
    ),
    "recommendations": dashboard(
        "sbi-reco",
        "Smart BI · Recommendations",
        [
            panel(
                "Requests / min by business type",
                "sum by (business_type) (rate(recommendation_requests_total[5m])) * 60",
                unit="short",
                legend="{{business_type}}",
            ),
            panel(
                "Median score by business type",
                "histogram_quantile(0.5, sum by (le, business_type) (rate(recommendation_score_bucket[1h])))",
                legend="{{business_type}}",
            ),
            panel(
                "Stability (top-5 Jaccard vs previous run)",
                "recommendation_stability_jaccard",
                "bargauge",
                "percentunit",
                8,
                9,
                "{{business_type}}",
                thresholds=[(0, RED), (0.6, AMBER), (0.8, GREEN)],
            ),
            panel(
                "Mean rank width of top 5 (p10–p90)",
                "recommendation_rank_width",
                "bargauge",
                "short",
                8,
                9,
                "{{business_type}}",
            ),
            panel(
                "Excluded for insufficient data",
                "sum by (business_type) (increase(recommendation_low_coverage_total[24h]))",
                "bargauge",
                "short",
                8,
                9,
                "{{business_type}}",
            ),
            panel(
                "User feedback (24 h)",
                "sum by (rating) (increase(user_feedback_total[24h]))",
                "stat",
                "short",
                24,
                5,
                "{{rating}}",
            ),
        ],
    ),
    "agent": dashboard(
        "sbi-agent",
        "Smart BI · AI Agent",
        [
            panel("Requests / min", "sum by (status) (rate(agent_requests_total[5m])) * 60", legend="{{status}}", w=8),
            panel(
                "Latency p50 / p95 (s)",
                [
                    "histogram_quantile(0.5, sum by (le) (rate(agent_latency_seconds_bucket[5m])))",
                    "histogram_quantile(0.95, sum by (le) (rate(agent_latency_seconds_bucket[5m])))",
                ],
                unit="s",
                w=8,
            ),
            panel("Tool calls / min", "sum by (tool) (rate(agent_tool_calls_total[5m])) * 60", legend="{{tool}}", w=8),
            panel(
                "Tokens (24 h)", "sum by (kind) (increase(agent_tokens_total[24h]))", "stat", "short", 6, 5, "{{kind}}"
            ),
            panel("Estimated cost (24 h)", "sum(increase(agent_cost_usd_total[24h]))", "stat", "currencyUSD", 6, 5),
            panel(
                "Unverified numbers (24 h)",
                "sum(increase(agent_verification_failures_total[24h]))",
                "stat",
                "short",
                6,
                5,
                thresholds=[(0, GREEN), (1, AMBER), (10, RED)],
            ),
            panel("RAG empty results (24 h)", "sum(increase(rag_empty_results_total[24h]))", "stat", "short", 6, 5),
            panel(
                "Tool failures / min",
                'sum by (tool) (rate(agent_tool_calls_total{status="error"}[5m])) * 60',
                legend="{{tool}}",
                w=12,
            ),
            panel(
                "MCP tool calls / min", "sum by (tool) (rate(mcp_tool_calls_total[5m])) * 60", legend="{{tool}}", w=12
            ),
            sql_panel(
                "Recent agent runs (Postgres)",
                "SELECT created_at, lang, mode, intent, status, latency_ms, tool_count, verification_failures, "
                "tokens_in + tokens_out AS tokens, round(cost_usd::numeric, 5) AS cost_usd, left(question, 120) AS question "
                "FROM agent_runs ORDER BY created_at DESC LIMIT 50",
            ),
        ],
    ),
    "api-infra": dashboard(
        "sbi-api",
        "Smart BI · API / Infra",
        [
            panel("Requests / s by handler", "sum by (handler) (rate(http_requests_total[5m]))", legend="{{handler}}"),
            panel(
                "Error rate (5xx)",
                'sum(rate(http_requests_total{status=~"5.."}[5m])) / clamp_min(sum(rate(http_requests_total[5m])), 1e-9)',
                unit="percentunit",
            ),
            panel(
                "Latency p95 by handler (s)",
                "histogram_quantile(0.95, sum by (le, handler) (rate(http_request_duration_seconds_bucket[5m])))",
                unit="s",
                legend="{{handler}}",
            ),
            panel("Postgres connections", "sum(pg_stat_activity_count)", legend="connections"),
        ],
    ),
}


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for name, d in DASHBOARDS.items():
        (OUT / f"{name}.json").write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{len(DASHBOARDS)} dashboards written to {OUT}")


if __name__ == "__main__":
    main()
