"""Ranking metrics for recommendation evaluation (PLAN.md Phase 11). Pure functions.

`ranked` is the system's ordered list of ids; `relevance` maps id → graded relevance (0–3).
An item is "relevant" when its grade is >= RELEVANT_GRADE.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

RELEVANT_GRADE = 2


def precision_at_k(ranked: Sequence[str], relevance: Mapping[str, float], k: int) -> float:
    top = ranked[:k]
    return sum(relevance.get(i, 0) >= RELEVANT_GRADE for i in top) / k if k else 0.0


def recall_at_k(ranked: Sequence[str], relevance: Mapping[str, float], k: int) -> float:
    relevant = {i for i, g in relevance.items() if g >= RELEVANT_GRADE}
    if not relevant:
        return 0.0
    return len(relevant & set(ranked[:k])) / len(relevant)


def dcg(gains: Sequence[float]) -> float:
    return sum((2**g - 1) / math.log2(i + 2) for i, g in enumerate(gains))


def ndcg_at_k(ranked: Sequence[str], relevance: Mapping[str, float], k: int) -> float:
    ideal = dcg(sorted(relevance.values(), reverse=True)[:k])
    return dcg([relevance.get(i, 0) for i in ranked[:k]]) / ideal if ideal else 0.0


def mrr(ranked: Sequence[str], relevance: Mapping[str, float]) -> float:
    for i, item in enumerate(ranked, 1):
        if relevance.get(item, 0) >= RELEVANT_GRADE:
            return 1.0 / i
    return 0.0
