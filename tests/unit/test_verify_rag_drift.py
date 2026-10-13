from __future__ import annotations

import numpy as np

from app.services.verify import extract_numbers, verify_answer
from monitoring.drift import jaccard, psi
from rag.ingest import chunk_text
from rag.retrieve import _tsquery, rrf

TOOLS = [{"value": 4382100.0, "pct_change": 12.34, "index": 112.3, "rate": 0.0456, "total": 397.4e12}]


def test_verifier_accepts_rescaled_and_rounded_numbers() -> None:
    answer = (
        "Population is 4.38 million (4,382,100 people), +12.3% (index 112.3), rate 4.6%, "
        "total 397.4 trillion UZS. Rank 3 in 2024. 80% interval shown."
    )
    assert verify_answer(answer, TOOLS) == {"checked": 6, "unsupported": []}


def test_verifier_catches_an_invented_number() -> None:
    v = verify_answer("Population is 5.9 million and grew 23%.", TOOLS)
    assert v["unsupported"] == ["5.9", "23"]


def test_numbers_from_the_question_and_links_are_not_claims() -> None:
    assert (
        verify_answer("With 700 million UZS see [SIAT 4462](https://x/4462.json)", [], "I have 700 million")[
            "unsupported"
        ]
        == []
    )
    assert [v for _, v in extract_numbers("1 234 567 and 12,5")] == [1234567.0, 12.5]


def test_chunking_overlaps() -> None:
    text = "\n\n".join(f"Paragraph {i}. " + "word " * 120 for i in range(12))
    chunks = chunk_text(text, size=1000, overlap=200)
    assert len(chunks) > 3 and all(len(c) <= 1000 for c in chunks)
    assert chunks[0][-100:].split()[-1] in chunks[1]  # overlap carries text over
    assert chunk_text("short") == ["short"]


def test_rrf_and_query_building() -> None:
    fused = rrf([(1, 9.0), (2, 5.0)], [(2, 0.9), (3, 0.8)])
    assert fused[0][0] == 2  # in both lists
    assert _tsquery("How is the permanent population defined?") == "permanent:* | population:* | defined:*"


def test_psi_and_jaccard() -> None:
    rng = np.random.default_rng(0)
    a = rng.normal(0, 1, 2000)
    assert psi(a, a) < 0.01
    assert psi(a, a + 1.5) > 0.2
    assert jaccard(["a", "b"], ["b", "c"]) == 1 / 3
