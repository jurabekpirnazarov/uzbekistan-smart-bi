"""Hybrid retrieval: Postgres full-text ranking (BM25-style) + optional embeddings, fused with RRF."""

from __future__ import annotations

import re

import numpy as np
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.models import RagChunk

RRF_K = 60
CANDIDATES = 30
_WORD = re.compile(r"[\w‘’ʻ']{2,}", re.UNICODE)
STOPWORDS = {
    "the", "and", "for", "what", "how", "is", "are", "of", "in", "to", "a", "an", "does", "do", "which",
    "qanday", "nima", "va", "bu", "uchun", "qaysi", "как", "что", "это", "для", "и", "в", "на", "по",
}  # fmt: skip


def _tsquery(query: str) -> str:
    words = [w.lower().strip("‘’ʻ'") for w in _WORD.findall(query)]
    words = [re.sub(r"[^\w]", "", w) for w in words if w.lower() not in STOPWORDS]
    words = [w for w in words if len(w) >= 2]
    # prefix match so "methodology" finds "methodological", OR so partial overlap still ranks
    return " | ".join(f"{w}:*" for w in dict.fromkeys(words))


def bm25(db: Session, query: str, k: int = CANDIDATES) -> list[tuple[int, float]]:
    q = _tsquery(query)
    if not q:
        return []
    rows = db.execute(
        text(
            """SELECT id, ts_rank_cd(tsv, to_tsquery('simple', :q), 32) AS score
               FROM rag_chunks WHERE tsv @@ to_tsquery('simple', :q)
               ORDER BY score DESC LIMIT :k"""
        ),
        {"q": q, "k": k},
    ).all()
    return [(int(i), float(s)) for i, s in rows]


def vector(db: Session, query_vec: list[float], k: int = CANDIDATES) -> list[tuple[int, float]]:
    rows = db.execute(select(RagChunk.id, RagChunk.embedding).where(RagChunk.embedding.is_not(None))).all()
    if not rows:
        return []
    ids = np.array([r[0] for r in rows])
    m = np.array([r[1] for r in rows], dtype=float)
    q = np.array(query_vec, dtype=float)
    sims = m @ q / (np.linalg.norm(m, axis=1) * np.linalg.norm(q) + 1e-12)
    top = np.argsort(-sims)[:k]
    return [(int(ids[i]), float(sims[i])) for i in top]


def rrf(*rankings: list[tuple[int, float]], k: int = RRF_K) -> list[tuple[int, float]]:
    """Reciprocal rank fusion: Σ 1 / (k + rank)."""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, (doc, _) in enumerate(ranking, 1):
            scores[doc] = scores.get(doc, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda x: -x[1])


def retrieve(db: Session, query: str, k: int = 5, query_vec: list[float] | None = None) -> list[dict]:
    lexical = bm25(db, query)
    semantic = vector(db, query_vec) if query_vec is not None else []
    fused = rrf(lexical, semantic) if semantic else rrf(lexical)
    top = fused[:k]
    if not top:
        return []
    chunks = {c.id: c for c in db.scalars(select(RagChunk).where(RagChunk.id.in_([i for i, _ in top]))).all()}
    return [
        {
            "doc_id": chunks[i].doc_id,
            "title": chunks[i].title,
            "source_url": chunks[i].source_url,
            "score": round(s, 5),
            "content": chunks[i].content,
        }
        for i, s in top
        if i in chunks
    ]
