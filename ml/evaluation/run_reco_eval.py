"""Recommendation evaluation: P@K, R@K, NDCG@K, MRR vs baselines, plus factor ablation (PLAN.md Phase 11)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import yaml
from sqlalchemy.orm import Session

from app.services import recommendations
from app.services import statistics as stats
from ml.evaluation.ranking_metrics import mrr, ndcg_at_k, precision_at_k, recall_at_k
from ml.scoring.profiles import load_profiles

GOLD = Path(__file__).resolve().parents[2] / "tests" / "eval" / "reco_gold.yaml"
KS = (3, 5)
RANDOM_RUNS = 200


def metrics_for(ranked: list[str], rel: dict[str, float]) -> dict[str, float]:
    out = {f"p@{k}": precision_at_k(ranked, rel, k) for k in KS}
    out |= {f"r@{k}": recall_at_k(ranked, rel, k) for k in KS}
    out |= {f"ndcg@{k}": ndcg_at_k(ranked, rel, k) for k in KS}
    out["mrr"] = mrr(ranked, rel)
    return out


def _system(db: Session, q: dict, weights: dict[str, float] | None = None) -> list[str]:
    req = recommendations.RecommendRequest(
        business_type=q["business_type"], region=q.get("region"), weights_override=weights, limit=250
    )
    return [r["entity"]["soato"] for r in recommendations.recommend(db, req, persist=False)["results"]]


def _population_only(db: Session, q: dict) -> list[str]:
    level = "district" if q.get("region") else "region"
    return [i.soato for i in stats.get_ranking(db, "population_total", level, None, q.get("region")).items]  # type: ignore[arg-type]


def run(db: Session) -> dict:
    gold = yaml.safe_load(GOLD.read_text(encoding="utf-8"))["queries"]
    profiles = load_profiles()
    rng = np.random.default_rng(0)
    per_query, system, popb, rand = [], [], [], []
    ablation: dict[str, list[float]] = {}
    for q in gold:
        rel = {str(k): float(v) for k, v in q["relevance"].items()}
        ranked = _system(db, q)
        m = metrics_for(ranked, rel)
        system.append(m)
        popb.append(metrics_for(_population_only(db, q), rel))
        rand.append(
            {
                k: float(np.mean([metrics_for(list(rng.permutation(ranked)), rel)[k] for _ in range(RANDOM_RUNS)]))
                for k in m
            }
        )
        per_query.append({"id": q["id"], "labelled_by": q.get("labelled_by", "?"), **m})
        base_ndcg = m["ndcg@5"]
        for f in profiles[q["business_type"]].active_factors():
            drop = _system(db, q, {f.feature: 0.0})
            ablation.setdefault(f.feature, []).append(ndcg_at_k(drop, rel, 5) - base_ndcg)

    def mean(rows: list[dict]) -> dict[str, float]:
        return {k: float(np.mean([r[k] for r in rows])) for k in rows[0]} if rows else {}

    return {
        "n_queries": len(gold),
        "placeholder_labels": sum(q.get("labelled_by") == "placeholder" for q in gold),
        "system": mean(system),
        "population_only": mean(popb),
        "random": mean(rand),
        "per_query": per_query,
        "ablation_delta_ndcg5": {k: float(np.mean(v)) for k, v in sorted(ablation.items())},
    }
