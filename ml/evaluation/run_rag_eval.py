"""RAG evaluation: hit@5, MRR and citation presence over methodology questions."""

from __future__ import annotations

from pathlib import Path

import yaml
from sqlalchemy.orm import Session

from app.services.documents import retrieve_documents

QUESTIONS = Path(__file__).resolve().parents[2] / "tests" / "eval" / "rag_questions.yaml"


def run(db: Session, k: int = 5) -> dict:
    qs = yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))["questions"]
    rows, mode = [], "bm25"
    for q in qs:
        res = retrieve_documents(db, q["q"], k)
        mode = res["mode"]
        ids = [h["doc_id"] for h in res["results"]]
        rank = next((i for i, d in enumerate(ids, 1) if d in q["expect"]), None)
        rows.append(
            {
                "q": q["q"],
                "expect": q["expect"],
                "top": ids[:3],
                "hit": rank is not None,
                "rr": 1 / rank if rank else 0.0,
                "cited": all(h.get("title") and (h.get("source_url") or h["doc_id"]) for h in res["results"]),
            }
        )
    n = len(rows)
    return {
        "mode": mode,
        "n_questions": n,
        "hit@5": sum(r["hit"] for r in rows) / n,
        "mrr": sum(r["rr"] for r in rows) / n,
        "citation_presence": sum(r["cited"] for r in rows) / n,
        "questions": rows,
    }
