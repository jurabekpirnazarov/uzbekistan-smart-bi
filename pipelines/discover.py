"""Discover datasets newly published on SIAT and map the safe ones into the existing schema.

Run by pipelines/refresh.py after `siat_ingest.py catalog --refresh`.

- The first run stores a baseline of all catalog ids (data/processed/catalog_seen.json); later runs only look
  at ids that were not in the catalog before.
- A new dataset is auto-mapped only if it is safe to load into `observations` without human decisions:
  annual, published by region and/or district, no extra breakdown dimensions (sex, activity, …), numeric,
  ≥ 2 years, and a unit we can normalise (people / UZS scales / units / percentages).
- Auto-mapped datasets get the internal code `siat_<id>` and are written to
  data/reference/indicator_map.auto.yaml with `auto_added: true`. They appear in the catalogue, analytics,
  map, API, MCP and chat, but are NOT used by the Business Opportunity Score until a person moves them into
  indicator_map.yaml with a proper code (CLAUDE.md rule 11 — a new indicator is a reviewed map entry).
- Everything else is listed in data/processed/discover_last.json for manual review.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
MAIN_MAP = ROOT / "data" / "reference" / "indicator_map.yaml"
AUTO_MAP = ROOT / "data" / "reference" / "indicator_map.auto.yaml"
SEEN = PROCESSED / "catalog_seen.json"
RESULT = PROCESSED / "discover_last.json"
MAX_NEW_PER_RUN = 25  # safety valve if SIAT republishes its whole catalogue with new ids

NON_ADDITIVE = re.compile(
    r"%|percent|per capita|per 1|average|rate|index|growth|share|ratio|density|coefficient|price index|average price",
    re.IGNORECASE,
)


# --- pure helpers (unit-tested) -------------------------------------------------------------------


def infer_unit(source_unit: str, name_en: str = "") -> tuple[str, float, bool] | None:
    """(stored unit, multiplier, additive) for a SIAT unit text, or None if it cannot be normalised safely."""
    u = (source_unit or "").strip().lower()
    text = f"{u} {name_en.lower()}"
    additive = not NON_ADDITIVE.search(text)
    money = any(w in u for w in ("soum", "sum", "uzs", "so'm", "so‘m"))
    if "%" in u or "percent" in u or "percentage" in u:
        return source_unit.strip(), 1.0, False
    if money:
        for words, mult in (
            (("trillion", "trln"), 1e12),
            (("billion", "bln", "mlrd"), 1e9),
            (("million", "mln"), 1e6),
            (("thousand", "thsd", "ths"), 1e3),
        ):
            if any(w in u for w in words):
                return "UZS", mult, additive
        return "UZS", 1.0, additive
    if any(w in u for w in ("people", "person", "persons")):
        return "persons", 1000.0 if ("thousand" in u or "thsd" in u) else 1.0, additive
    if u in ("units", "unit", "quantity", "number", "pcs", "pieces"):
        return "units", 1.0, additive
    return None


def infer_category(category_path: str) -> str:
    p = (category_path or "").lower()
    if "demograph" in p or "population" in p:
        return "population"
    if any(w in p for w in ("enterprise", "entrepreneur", "business", "small business")):
        return "business"
    if "health" in p:
        return "health"
    if any(w in p for w in ("service", "trade", "retail")):
        return "services"
    return "economy"


def eligibility(rows: pd.DataFrame) -> str | None:
    """None if the processed observations of one dataset can be auto-loaded, else the reason why not."""
    if rows.empty:
        return "no observations after normalisation"
    annual = rows[rows["freq"].astype(str).str.upper().eq("A")]
    if annual.empty:
        return "not annual"
    if not annual["level"].isin(["region", "district"]).any():
        return "no region or district breakdown"
    dims = annual["dimensions"].fillna("").astype(str).str.strip()
    if (dims != "").any():
        return "has extra breakdown dimensions (needs a manual mapping)"
    if annual["year"].nunique() < 2:
        return "fewer than 2 years"
    key = ["level", "soato_code", "year"]
    if annual.duplicated(key).any():
        return "several values per territory and year"
    return None


# --- main ---------------------------------------------------------------------------------------


def mapped_ids() -> set[int]:
    ids: set[int] = set()
    for path in (MAIN_MAP, AUTO_MAP):
        if path.exists():
            m = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            ids |= {int(s["siat_dataset_id"]) for s in (m.get("indicators") or {}).values()}
            ids |= {int(r["siat_dataset_id"]) for r in (m.get("reference") or {}).values()}
    return ids


def write_result(result: dict) -> None:
    RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("DISCOVER " + json.dumps({k: result[k] for k in ("new_in_catalog", "added", "skipped_count")}))


def main() -> None:
    catalog = pd.read_csv(PROCESSED / "catalog.csv")
    ids_now = {int(i) for i in catalog["dataset_id"]}
    now = datetime.now(UTC).isoformat(timespec="seconds")
    if not SEEN.exists():
        SEEN.write_text(json.dumps({"baseline_at": now, "ids": sorted(ids_now)}), encoding="utf-8")
        write_result(
            {"at": now, "baseline": True, "new_in_catalog": [], "added": [], "skipped": [], "skipped_count": 0}
        )
        return
    seen = set(json.loads(SEEN.read_text(encoding="utf-8"))["ids"])
    new_ids = sorted(ids_now - seen - mapped_ids())
    cat = catalog.set_index("dataset_id")
    annual_new = [i for i in new_ids if str(cat.loc[i, "period"]).strip().lower() in ("yillik", "annual", "годовая")]
    skipped = [
        {"dataset_id": i, "name_en": cat.loc[i, "name_en"], "reason": "not annual"}
        for i in new_ids
        if i not in annual_new
    ]
    candidates = annual_new[:MAX_NEW_PER_RUN]
    skipped += [
        {"dataset_id": i, "name_en": cat.loc[i, "name_en"], "reason": "over the per-run limit, next run"}
        for i in annual_new[MAX_NEW_PER_RUN:]
    ]

    added = []
    if candidates:
        subprocess.run(
            [sys.executable, "pipelines/siat_ingest.py", "fetch", "--ids", *map(str, candidates)], cwd=ROOT, check=True
        )
        obs = pd.read_csv(PROCESSED / "observations.csv", dtype={"soato_code": str}, low_memory=False)
        meta = pd.read_csv(PROCESSED / "indicators.csv").set_index("dataset_id")
        auto = (yaml.safe_load(AUTO_MAP.read_text(encoding="utf-8")) if AUTO_MAP.exists() else None) or {}
        auto.setdefault("indicators", {})
        for i in candidates:
            name = str(meta.loc[i, "name_en"]) if i in meta.index else str(cat.loc[i, "name_en"])
            reason = eligibility(obs[obs["dataset_id"] == i])
            unit_text = str(meta.loc[i, "unit"]) if i in meta.index else ""
            unit = infer_unit(unit_text, name) if reason is None else None
            if reason is None and unit is None:
                reason = f"unit not recognised: '{unit_text}'"
            if reason:
                skipped.append({"dataset_id": i, "name_en": name, "reason": reason})
                continue
            stored, mult, additive = unit
            code = f"siat_{i}"
            auto["indicators"][code] = {
                "siat_dataset_id": i,
                "name_en": name,
                "category": infer_category(str(cat.loc[i, "category_path"])),
                "source_unit": unit_text,
                "unit": stored,
                "unit_multiplier": mult,
                "additive": additive,
                "higher_is_better": True,
                "auto_added": True,
                "added_at": now,
            }
            added.append({"dataset_id": i, "code": code, "name_en": name, "unit": stored})
        if added:
            header = (
                "# Auto-mapped SIAT datasets (pipelines/discover.py). Loaded into the same schema as\n"
                "# indicator_map.yaml but flagged auto_added and excluded from scoring. To promote one, move it to\n"
                "# indicator_map.yaml with a meaningful internal code and delete it here.\n"
            )
            AUTO_MAP.write_text(header + yaml.safe_dump(auto, allow_unicode=True, sort_keys=False), encoding="utf-8")

    SEEN.write_text(
        json.dumps(
            {
                "baseline_at": json.loads(SEEN.read_text(encoding="utf-8"))["baseline_at"],
                "ids": sorted(
                    seen | set(new_ids) - {int(s["dataset_id"]) for s in skipped if "next run" in s["reason"]}
                ),
            }
        ),
        encoding="utf-8",
    )
    write_result(
        {
            "at": now,
            "baseline": False,
            "new_in_catalog": new_ids,
            "added": added,
            "skipped": skipped,
            "skipped_count": len(skipped),
        }
    )


if __name__ == "__main__":
    main()
