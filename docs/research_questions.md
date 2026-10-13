# Research questions → experiments and evidence

| # | Question | Experiment | Metric | Where |
|---|---|---|---|---|
| 1 | How well can official statistics be turned into business features? | Feature coverage by level and year; factor ablation | Coverage table; ΔNDCG@5 per factor | `python -m ml.features.pipeline` output, `docs/features.md`, `docs/evaluation_report.md` §1 |
| 2 | Can an agent autonomously select and combine statistical tools and models? | `tests/eval/agent_cases.yaml` in LLM and rule-based mode | Tool-selection accuracy, task success, numeric faithfulness, insufficient-data detection, latency, cost | `docs/evaluation_report.md` §3, Monitoring page |
| 3 | How accurately can business indicators be forecast? | Rolling-origin backtest, 3 origins, horizons 1–2, 5 models incl. naive baselines | MAE, RMSE, MAPE, sMAPE, % improvement over `naive_last` | `docs/evaluation_report.md` §2, MLflow |
| 4 | How effective are the location recommendations? | Expert-labelled gold set (≥ 30 queries) vs population-only and random baselines | P@K, R@K, NDCG@K (K = 3, 5), MRR | `docs/evaluation_report.md` §1 (**labels pending: placeholders now**) |
| 5 | How can quality be monitored continuously? | Batch + live metrics, drift (PSI), realised error, recommendation stability, alerts | Alert coverage, PSI, Jaccard stability | `docs/monitoring.md`, Grafana, Monitoring page |
| 6 | Does geospatial visualisation improve decisions? | Small user study (5–8 people): same task with and without the map | Time to decision, confidence (1–5), answer quality | Protocol below |

## Protocol for question 6

1. Recruit 5–8 participants (entrepreneurs or analysts).
2. Task A: "Pick the best district in a given region for business X" using only the Analytics page tables.
3. Task B: the same task for another region/business using the Map + Recommend pages.
4. Counter-balance the order between participants. Record time to decision and self-reported confidence.
5. Compare with a paired test; report medians and individual results (small sample — no strong claims).
