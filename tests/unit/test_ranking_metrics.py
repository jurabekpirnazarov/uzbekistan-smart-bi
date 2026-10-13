from __future__ import annotations

import math

import pytest

from ml.evaluation.ranking_metrics import mrr, ndcg_at_k, precision_at_k, recall_at_k

RANKED = ["a", "b", "c", "d"]
REL = {"a": 3, "b": 0, "c": 2, "e": 2}


def test_precision_recall() -> None:
    assert precision_at_k(RANKED, REL, 3) == pytest.approx(2 / 3)
    assert recall_at_k(RANKED, REL, 3) == pytest.approx(2 / 3)  # a, c of {a, c, e}
    assert recall_at_k(RANKED, {}, 3) == 0.0


def test_ndcg_known_value() -> None:
    dcg = (2**3 - 1) / math.log2(2) + 0 + (2**2 - 1) / math.log2(4)
    idcg = (2**3 - 1) / math.log2(2) + (2**2 - 1) / math.log2(3) + (2**2 - 1) / math.log2(4)
    assert ndcg_at_k(RANKED, REL, 3) == pytest.approx(dcg / idcg)
    assert ndcg_at_k(["a", "c", "e"], REL, 3) == pytest.approx(1.0)


def test_mrr() -> None:
    assert mrr(["b", "c"], REL) == 0.5
    assert mrr(["b"], REL) == 0.0
