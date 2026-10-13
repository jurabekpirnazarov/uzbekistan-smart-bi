"""Generate docs/schema.md (Mermaid ER diagram + column tables) from the SQLAlchemy models.

Usage:  python -m app.db.schema_doc     (from the repository root, backend/ on PYTHONPATH)
"""

from __future__ import annotations

from pathlib import Path

from app.db import models  # noqa: F401  (registers tables)
from app.db.base import Base

ROOT = Path(__file__).resolve().parents[3]

GROUPS = {
    "Official data (warehouse)": [
        "data_sources",
        "regions",
        "districts",
        "indicators",
        "observations",
        "ingestion_runs",
    ],
    "Analytics": ["features", "recommendations", "predictions", "model_metrics"],
    "AI agent and RAG": ["agent_runs", "agent_tool_calls", "feedback", "rag_chunks"],
    "Operations": ["pipeline_runs", "monitor_metrics"],
}
# Columns managed by raw SQL in the migrations (not mapped in the ORM).
RAW_COLUMNS = {
    "regions": [("geom", "geometry(MultiPolygon,4326)", "PostGIS boundary")],
    "districts": [("geom", "geometry(MultiPolygon,4326)", "PostGIS boundary (NULL when approximate)")],
    "rag_chunks": [("tsv", "tsvector", "generated full-text vector (BM25-style search)")],
}
# Logical links that are not foreign keys (SOATO / indicator codes).
LOGICAL = [
    ("predictions", "indicators", "indicator_code"),
    ("recommendations", "regions", "region_soato"),
    ("feedback", "agent_runs", "request_id"),
]


def mermaid_type(col) -> str:  # noqa: ANN001
    t = str(col.type).split("(")[0].lower()
    return {"double precision": "float", "varchar": "string", "smallint": "int", "bigint": "bigint"}.get(t, t)


def main() -> None:
    tables = Base.metadata.tables
    er = ["```mermaid", "erDiagram"]
    for name in [t for g in GROUPS.values() for t in g]:
        t = tables[name]
        er.append(f"  {name} {{")
        for c in t.columns:
            tag = " PK" if c.primary_key else (" FK" if c.foreign_keys else "")
            er.append(f"    {mermaid_type(c)} {c.name}{tag}")
        for col, typ, _ in RAW_COLUMNS.get(name, []):
            er.append(f"    {typ.split('(')[0]} {col}")
        er.append("  }")
    for t in tables.values():
        for fk in t.foreign_keys:
            er.append(f'  {fk.column.table.name} ||--o{{ {t.name} : "{fk.parent.name}"')
    for child, parent, col in LOGICAL:
        er.append(f'  {parent} ||..o{{ {child} : "{col}"')
    er.append("```")

    lines = [
        "# Database schema",
        "",
        "_Generated from `backend/app/db/models.py` by `python -m app.db.schema_doc`. PostgreSQL 16 + PostGIS;"
        " migrations in `backend/alembic/versions/` (`python manage.py migrate`)._",
        "",
        "Solid lines are foreign keys; dotted lines are logical links by code (SOATO / indicator code / request id).",
        "",
        *er,
        "",
    ]
    for group, names in GROUPS.items():
        lines += [f"## {group}", ""]
        for name in names:
            t = tables[name]
            doc = (t.comment or "").strip()
            lines += [
                f"### `{name}`" + (f" — {doc}" if doc else ""),
                "",
                "| Column | Type | Null | Key / notes |",
                "|---|---|---|---|",
            ]
            for c in t.columns:
                key = (
                    "PK"
                    if c.primary_key
                    else ", ".join(f"FK → {fk.column.table.name}.{fk.column.name}" for fk in c.foreign_keys)
                )
                lines.append(f"| `{c.name}` | {str(c.type).lower()} | {'yes' if c.nullable else 'no'} | {key} |")
            for col, typ, note in RAW_COLUMNS.get(name, []):
                lines.append(f"| `{col}` | {typ} | yes | {note} (raw SQL) |")
            uniques = [
                ", ".join(c.name for c in u.columns)
                for u in t.constraints
                if u.__class__.__name__ == "UniqueConstraint"
            ]
            idx = [", ".join(c.name for c in i.columns) for i in t.indexes]
            extra = [f"unique ({u})" for u in uniques] + [f"index ({i})" for i in idx]
            if extra:
                lines += ["", "Constraints: " + " · ".join(extra)]
            lines.append("")
    (ROOT / "docs" / "schema.md").write_text("\n".join(lines), encoding="utf-8")
    print("docs/schema.md written")


if __name__ == "__main__":
    main()
