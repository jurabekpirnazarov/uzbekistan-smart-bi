"""Methodology / documentation search for the agent and MCP (wraps rag/retrieve.py)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core import metrics
from app.core.config import get_settings
from app.core.logging import get_logger
from rag.retrieve import retrieve

log = get_logger("rag")


def _embed_query(query: str) -> list[float] | None:
    s = get_settings()
    if not s.openai_api_key:
        return None
    try:
        from openai import OpenAI

        return (
            OpenAI(api_key=s.openai_api_key)
            .embeddings.create(model=s.openai_embed_model, input=[query])
            .data[0]
            .embedding
        )
    except Exception as e:  # fall back to BM25 only
        log.warning("embed_failed", error=type(e).__name__)
        return None


def retrieve_documents(db: Session, query: str, k: int = 5) -> dict:
    """Top-k chunks with citations. Uses embeddings only if the index has them and a key is set."""
    from sqlalchemy import func, select

    from app.db.models import RagChunk

    has_vectors = db.scalar(select(func.count(RagChunk.id)).where(RagChunk.embedding.is_not(None))) or 0
    qv = _embed_query(query) if has_vectors else None
    hits = retrieve(db, query, k=max(1, min(k, 10)), query_vec=qv)
    if hits:
        metrics.RAG_TOP_SCORE.observe(hits[0]["score"])
    else:
        metrics.RAG_EMPTY.inc()
    return {
        "query": query,
        "mode": "hybrid" if qv is not None else "bm25",
        "results": [{**h, "content": h["content"][:1500]} for h in hits],
        "warnings": [] if hits else ["No matching documents in the index."],
    }
