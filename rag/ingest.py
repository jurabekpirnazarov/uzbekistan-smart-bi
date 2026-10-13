"""Build the RAG index (PLAN.md Phase 8): SIAT methodology metadata, project docs, profiles, features.

Usage:  python -m rag.ingest        (part of `python manage.py seed --local`)

Chunks ≈ 800 tokens with 100-token overlap (≈ 4 characters per token). Full-text (BM25-style) search
always works; OpenAI embeddings are added when OPENAI_API_KEY is set (stored as JSON, cosine in Python,
because pgvector is optional — CLAUDE.md rule 10).
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml
from sqlalchemy import delete, insert

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.db.models import RagChunk  # noqa: E402

CHUNK_CHARS = 3200  # ≈ 800 tokens
OVERLAP_CHARS = 400  # ≈ 100 tokens
EMBED_BATCH = 64


@dataclass
class Doc:
    doc_id: str
    title: str
    source_url: str | None
    text: str


def chunk_text(text: str, size: int = CHUNK_CHARS, overlap: int = OVERLAP_CHARS) -> list[str]:
    """Split on paragraph boundaries where possible; consecutive chunks overlap by `overlap` chars."""
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []
    chunks, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            cut = text.rfind("\n\n", start + size // 2, end)
            if cut == -1:
                cut = text.rfind(". ", start + size // 2, end)
            end = cut + 1 if cut != -1 else end
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return [c for c in chunks if c]


def siat_docs() -> list[Doc]:
    path = ROOT / "data" / "processed" / "indicators.csv"
    if not path.exists():
        return []
    imap = yaml.safe_load((ROOT / "data" / "reference" / "indicator_map.yaml").read_text(encoding="utf-8"))
    code_by_id = {v["siat_dataset_id"]: k for k, v in imap["indicators"].items()}
    docs = []
    for r in pd.read_csv(path).fillna("").itertuples(index=False):
        meta_lines = []
        try:
            for m in json.loads(r.metadata_json or "[]"):
                if m.get("value_en"):
                    meta_lines.append(f"{m.get('name_en')}: {m.get('value_en')}")
        except json.JSONDecodeError:
            pass
        code = code_by_id.get(int(r.dataset_id))
        text = "\n".join(
            [
                f"SIAT dataset {r.dataset_id} ({r.siat_code}).",
                f"Internal indicator code: {code}." if code else "Not mapped to an internal indicator.",
                f"English: {r.name_en}. Uzbek: {r.name_uz}. Russian: {r.name_ru}.",
                f"Category: {r.category_path}. Unit in source: {r.unit}. Periodicity: {r.periodicity}.",
                f"Source organisation: {r.source_org}.",
                "",
                f"Methodology: {r.methodology}",
                "",
                *meta_lines,
            ]
        )
        docs.append(Doc(f"siat:{r.dataset_id}", f"SIAT {r.dataset_id}: {r.name_en}", r.source_url or None, text))
    return docs


def markdown_docs() -> list[Doc]:
    docs = []
    for path in sorted((ROOT / "docs").glob("*.md")) + sorted((ROOT / "data" / "docs").glob("*.md")):
        text = path.read_text(encoding="utf-8")
        title = next((ln.lstrip("# ").strip() for ln in text.splitlines() if ln.startswith("#")), path.stem)
        docs.append(Doc(f"doc:{path.stem}", title, path.relative_to(ROOT).as_posix(), text))
    return docs


def profile_docs() -> list[Doc]:
    docs = []
    for path in sorted((ROOT / "ml" / "profiles").glob("*.yaml")):
        if path.name.startswith("_"):
            continue
        p = yaml.safe_load(path.read_text(encoding="utf-8"))
        lines = [
            f"Business profile '{p['business_type']}' — {p['display_name']['en']} "
            f"(uz: {p['display_name']['uz']}, ru: {p['display_name']['ru']}).",
            f"Typical minimum budget: {p['min_budget_uzs']:,} UZS. Default level: {p['default_level']}.",
            f"Normalisation: {p.get('normalization', 'percentile')}. Factors of the Business Opportunity Score:",
        ]
        lines += [
            f"- {f['label']}: feature {f['feature']}, weight {f['weight']}, direction {f['direction']}"
            for f in p["factors"]
        ]
        docs.append(
            Doc(
                f"profile:{p['business_type']}",
                f"Scoring profile: {p['display_name']['en']}",
                path.relative_to(ROOT).as_posix(),
                "\n".join(lines),
            )
        )
    feats = yaml.safe_load((ROOT / "ml" / "features" / "definitions.yaml").read_text(encoding="utf-8"))
    text = "Feature definitions used by the Business Opportunity Score:\n" + "\n".join(
        f"- {k}: type {v['type']}, inputs {', '.join(str(x) for kk, x in v.items() if kk != 'type')}"
        for k, v in feats.items()
    )
    docs.append(Doc("features:definitions", "Feature definitions", "ml/features/definitions.yaml", text))
    return docs


def embed(texts: list[str]) -> list[list[float]] | None:
    from app.core.config import get_settings

    s = get_settings()
    if not s.openai_api_key:
        return None
    from openai import OpenAI

    client = OpenAI(api_key=s.openai_api_key)
    out: list[list[float]] = []
    for i in range(0, len(texts), EMBED_BATCH):
        resp = client.embeddings.create(model=s.openai_embed_model, input=texts[i : i + EMBED_BATCH])
        out += [d.embedding for d in resp.data]
    return out


def main() -> None:
    from app.db.session import get_sessionmaker

    docs = siat_docs() + markdown_docs() + profile_docs()
    rows = []
    for d in docs:
        for i, c in enumerate(chunk_text(d.text)):
            rows.append(
                {"doc_id": d.doc_id, "title": d.title, "source_url": d.source_url, "chunk_index": i, "content": c}
            )
    try:
        vectors = embed([f"{r['title']}\n{r['content']}" for r in rows])
    except Exception as e:  # embeddings are optional; BM25 still works
        print(f"embeddings skipped ({type(e).__name__}) — BM25 only")
        vectors = None
    if vectors:
        for r, v in zip(rows, vectors, strict=True):
            r["embedding"] = v
    with get_sessionmaker()() as db:
        db.execute(delete(RagChunk))
        db.execute(insert(RagChunk), rows)
        db.commit()
    mode = "hybrid (BM25 + embeddings)" if vectors else "BM25 only"
    print(f"RAG index: {len(docs)} documents → {len(rows)} chunks, {mode}")


if __name__ == "__main__":
    main()
