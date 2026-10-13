# Monitoring

Three layers:

1. **Live metrics** — counters and histograms updated in-process, exposed on `GET /metrics`
   (backend :8000) and `GET /metrics` on the MCP server (:8100).
2. **Batch metrics** — `python manage.py monitor` (`monitoring/drift.py`) writes data-quality, drift,
   realised-error, model and stability metrics to the `monitor_metrics` table; the backend exports the
   latest snapshot as gauges at scrape time (no Pushgateway).
3. **Views** — the in-app **Monitoring** page (`/monitoring`, works without Docker), Grafana dashboards
   (Docker stack) and MLflow (:5000) for training and evaluation runs.

## Metrics

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `http_requests_total`, `http_request_duration_seconds` | counter / histogram | handler, method, status | API traffic (prometheus-fastapi-instrumentator) |
| `agent_requests_total` | counter | intent, status, lang | chat requests; status `ok / error / insufficient` |
| `agent_latency_seconds` | histogram | mode | end-to-end chat latency (`llm` / `fallback`) |
| `agent_tool_calls_total`, `agent_tool_latency_seconds` | counter / histogram | tool, status | tool usage by the agent |
| `agent_tokens_total`, `agent_cost_usd_total` | counter | kind, model | LLM tokens and estimated cost |
| `agent_verification_failures_total` | counter | — | numbers in answers that no tool result supports |
| `rag_retrieval_top_score`, `rag_empty_results_total` | histogram / counter | — | retrieval quality |
| `mcp_tool_calls_total`, `mcp_tool_latency_seconds` | counter / histogram | tool, status | MCP usage |
| `recommendation_requests_total`, `recommendation_score` | counter / histogram | business_type | scoring usage and score distribution |
| `recommendation_low_coverage_total` | counter | business_type | territories excluded for insufficient data |
| `user_feedback_total` | counter | rating | 👍 / 👎 |
| `ingestion_runs_total`, `ingestion_rows_total` | gauge (batch) | source, status / result | loader runs and rows |
| `data_last_update_timestamp` | gauge (batch) | source | freshness (alert after 45 days) |
| `pipeline_last_success_timestamp`, `pipeline_runs_total` | gauge (batch) | — / status | scheduled refresh health (alert after 7 days without success) |
| `data_quality_check_passed` | gauge (batch) | check | 1 = pass (see below) |
| `data_missing_ratio` | gauge (batch) | indicator | missing district-year cells |
| `model_backtest_smape` | gauge (batch) | indicator, level, model | selected model's backtest error |
| `feature_drift_psi` | gauge (batch) | feature, years | PSI previous vs latest year (alert > 0.2) |
| `prediction_realized_error` | gauge (batch) | indicator, model | MAPE of a forecast made one year earlier vs the latest official value |
| `recommendation_stability_jaccard` | gauge (batch) | business_type | top-5 overlap with the previous reference run |
| `recommendation_rank_width` | gauge (batch) | business_type | mean p10–p90 rank width of the top 5 |

Quality checks: SIAT quality report has 0 failures · no negative additive values · district population
sums to regions (< 0.5 %) · every region has a polygon · every district is located · features are up to
date with observations.

## Drift and stability

- **Feature drift:** PSI with 10 quantile bins from the previous year; years where < 80 % of districts are
  published are skipped. PSI > 0.2 → alert. Real alerts appear today for business growth (2026 break) and
  services per capita — they are data changes to review, not bugs.
- **Prediction drift:** each monitor run refits the selected model on history up to last year − 1 and
  measures the error against the latest official value.
- **Recommendation stability:** fixed reference queries (each business type, nationwide) are re-scored on
  every run; the top-5 Jaccard against the previous run and the Monte Carlo rank width are recorded.

## Grafana dashboards (Docker stack)

Provisioned from `monitoring/grafana/dashboards/`:

1. **Data Health** — freshness, quality checks, missing ratios, ingestion runs.
2. **ML Models** — backtest sMAPE per target, realised error, feature PSI.
3. **Recommendations** — request rate, score distribution, stability, low coverage, feedback.
4. **Agent** — requests/min, p50/p95 latency, tool calls & failures, tokens & cost, verification failures,
   RAG empties, and a table of recent runs read from Postgres.
5. **API / Infra** — request rate, error rate, latency.

## Alerts (`monitoring/prometheus/alerts.yml`)

Ingestion failures · data older than 45 days · agent error rate > 10 % (5 min) · agent p95 > 20 s ·
PSI > 0.2 · backtest sMAPE above 30 % for a selected model · any failed data-quality check.

## Verify

```powershell
python manage.py monitor
start http://localhost:5174/monitoring
curl http://localhost:8000/metrics
# Docker stack only:
start http://localhost:3000/dashboards
start http://localhost:9090/alerts
```
