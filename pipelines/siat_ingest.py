#!/usr/bin/env python3
"""
siat_ingest.py — Download official statistics from SIAT (siat.stat.uz) and turn
them into clean, structured, source-traceable tables.

Part of: Uzbekistan Smart Business Intelligence (pipelines/siat_ingest.py)

SIAT endpoints used (public, no key required):
    Catalog : GET https://siat.stat.uz/api/sdmx/json/
    Dataset : GET https://siat.stat.uz/media/uploads/sdmx/sdmx_data_{id}.json
(Endpoint discovery credit: github.com/alishersuyunov/siat-mcp, MIT.)

Outputs (default: ./data):
    raw/siat/catalog.json                    raw catalog tree
    raw/siat/datasets/{id}.json              raw dataset payloads (never modified)
    processed/catalog.csv                    flat list of all leaf datasets + category path
    processed/indicators.csv                 one row per downloaded dataset (name, unit, period, metadata)
    processed/observations.csv               long format: one row per (dataset, territory, dims, period)
    processed/regions.csv                    SOATO reference for the 14 regions
    processed/quality_report.json            validation results per dataset
    processed/ingestion_log.csv              one row per download attempt
    siat.db                                  SQLite with the same tables (for quick SQL)
    (optional) PostgreSQL via --database-url

Usage:
    pip install requests pandas            # sqlalchemy + psycopg only if you use --database-url
    python siat_ingest.py catalog                         # download + list all datasets
    python siat_ingest.py search "population"             # search the catalog
    python siat_ingest.py fetch --preset business         # business-relevant datasets
    python siat_ingest.py fetch --ids 123 456             # specific dataset ids
    python siat_ingest.py fetch --query "retail" --max 20
    python siat_ingest.py fetch --all                     # everything (slow, be polite)
    python siat_ingest.py rebuild                         # re-parse raw files, no network
    python siat_ingest.py selftest                        # offline parser test

Design rules (from CLAUDE.md):
    * Every value keeps its source: dataset_id, source_url, retrieved_at, raw sha256.
    * Nothing is imputed or invented. Unparseable values are dropped and counted.
    * is_synthetic is always False here — this script only handles official data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = "https://siat.stat.uz"
CATALOG_URL = f"{BASE_URL}/api/sdmx/json/"
DATA_URL = BASE_URL + "/media/uploads/sdmx/sdmx_data_{id}.json"
SOURCE_NAME = "SIAT"

HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "en",
    "origin": BASE_URL,
    "referer": f"{BASE_URL}/",
    "user-agent": "uz-smart-bi/1.0 (research prototype)",
}

LANGS = ("en", "uz", "ru", "uzc")

# The 14 first-level territories with SOATO codes. Names include common spellings
# so rows without a code can still be matched by name.
REGIONS: list[dict[str, Any]] = [
    {"soato": "1735", "name_en": "Republic of Karakalpakstan", "name_uz": "Qoraqalpog'iston Respublikasi",
     "aliases": ["karakalpak", "qoraqalpog", "каракалпак"]},
    {"soato": "1703", "name_en": "Andijan region", "name_uz": "Andijon viloyati", "aliases": ["andijan", "andijon", "андижан"]},
    {"soato": "1706", "name_en": "Bukhara region", "name_uz": "Buxoro viloyati", "aliases": ["bukhara", "buxoro", "бухар"]},
    {"soato": "1708", "name_en": "Jizzakh region", "name_uz": "Jizzax viloyati", "aliases": ["jizzakh", "jizzax", "джизак"]},
    {"soato": "1710", "name_en": "Kashkadarya region", "name_uz": "Qashqadaryo viloyati", "aliases": ["kashkadar", "qashqadar", "кашкадар"]},
    {"soato": "1712", "name_en": "Navoi region", "name_uz": "Navoiy viloyati", "aliases": ["navoi", "navoiy", "навои"]},
    {"soato": "1714", "name_en": "Namangan region", "name_uz": "Namangan viloyati", "aliases": ["namangan", "наманган"]},
    {"soato": "1718", "name_en": "Samarkand region", "name_uz": "Samarqand viloyati", "aliases": ["samarkand", "samarqand", "самарканд"]},
    {"soato": "1722", "name_en": "Surkhandarya region", "name_uz": "Surxondaryo viloyati", "aliases": ["surkhandar", "surxondar", "сурхандар"]},
    {"soato": "1724", "name_en": "Syrdarya region", "name_uz": "Sirdaryo viloyati", "aliases": ["syrdar", "sirdar", "сырдар"]},
    {"soato": "1726", "name_en": "Tashkent city", "name_uz": "Toshkent shahri", "aliases": ["tashkent city", "toshkent sh", "г. ташкент", "город ташкент"]},
    {"soato": "1727", "name_en": "Tashkent region", "name_uz": "Toshkent viloyati", "aliases": ["tashkent region", "toshkent viloyati", "ташкентская"]},
    {"soato": "1730", "name_en": "Fergana region", "name_uz": "Farg'ona viloyati", "aliases": ["fergana", "farg'ona", "fargʻona", "fargona", "ферган"]},
    {"soato": "1733", "name_en": "Khorezm region", "name_uz": "Xorazm viloyati", "aliases": ["khorezm", "xorazm", "хорезм"]},
]
REGION_CODES = {r["soato"] for r in REGIONS}
COUNTRY_ALIASES = ["republic of uzbekistan", "o'zbekiston respublikasi", "oʻzbekiston respublikasi",
                   "республика узбекистан", "uzbekistan", "o'zbekiston"]

# Keyword groups used by --preset business. Matched (case-insensitive) against
# dataset names in all languages. Each match is tagged with the group as `topic`.
BUSINESS_PRESET: dict[str, list[str]] = {
    "population": ["population", "численность населения", "aholi soni", "population density",
                   "urban population", "births", "migration"],
    "income": ["average monthly wage", "nominal wage", "среднемесячная", "o'rtacha oylik",
               "income", "доход", "daromad"],
    "labour": ["employment", "employed", "unemploy", "занят", "безработ", "bandlik", "ishsiz"],
    "business": ["enterprise", "organizations", "small business", "entrepreneur", "предприят",
                 "субъект", "korxona", "tadbirkor", "kichik biznes"],
    "trade": ["retail trade", "retail turnover", "розничн", "chakana", "wholesale", "оптов", "ulgurji"],
    "services": ["market services", "services", "услуг", "xizmat", "catering", "общественного питания"],
    "economy": ["gross regional product", "grp", "валовой региональный", "yalpi hududiy",
                "investment", "инвестиц", "investitsiya"],
    "industry": ["industrial production", "промышленн", "sanoat", "construction", "строител", "qurilish"],
    "agriculture": ["agricultur", "сельск", "qishloq xo'jalik"],
    "prices": ["consumer price", "индекс потребительских", "iste'mol narx"],
}

# Columns in SIAT data rows that are labels, not periods.
LABEL_KEYS_EXACT = {"Code", "code", "Klassifikator", "id", "ID"}
LABEL_KEY_PREFIXES = ("Klassifikator",)

PERIOD_PATTERNS = [
    (re.compile(r"^(\d{4})$"), "A"),
    (re.compile(r"^(\d{4})[-_ ]?(?:Q|K|кв\.?)?\s*([1-4]|I{1,3}|IV)\s*(?:Q|кв\.?|chorak)?$", re.I), "Q"),
    (re.compile(r"^(\d{4})[-_.](\d{1,2})$"), "M"),
    (re.compile(r"^(\d{1,2})[-_.](\d{4})$"), "M_rev"),
    (re.compile(r"^(\d{4})\s*[-–]\s*(?:jan|yan|янв)\w*\s*[-–]?\s*(\w+)$", re.I), "YTD"),
]
ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4}

MISSING_TOKENS = {"", "-", "–", "—", "…", "...", "x", "х", "n/a", "na", "null", "none", ".."}

log = logging.getLogger("siat_ingest")


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

@dataclass
class Paths:
    root: Path

    @property
    def raw(self) -> Path:
        return self.root / "raw" / "siat"

    @property
    def raw_datasets(self) -> Path:
        return self.raw / "datasets"

    @property
    def processed(self) -> Path:
        return self.root / "processed"

    @property
    def sqlite(self) -> Path:
        return self.root / "siat.db"

    def ensure(self) -> None:
        for p in (self.raw, self.raw_datasets, self.processed):
            p.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def make_session() -> requests.Session:
    s = requests.Session()
    retry = Retry(total=4, backoff_factor=1.5, status_forcelist=(429, 500, 502, 503, 504),
                  allowed_methods=("GET",), raise_on_status=False)
    s.mount("https://", HTTPAdapter(max_retries=retry, pool_maxsize=8))
    s.headers.update(HEADERS)
    return s


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

def node_name(node: dict, lang: str = "en") -> str:
    for k in (f"name_{lang}", "name_en", "name_uz", "name_ru", "name"):
        if node.get(k):
            return str(node[k]).strip()
    return str(node.get("id", ""))


def download_catalog(session: requests.Session, paths: Paths, refresh: bool = False) -> list[dict]:
    target = paths.raw / "catalog.json"
    if target.exists() and not refresh:
        age_h = (time.time() - target.stat().st_mtime) / 3600
        if age_h < 24:
            log.info("Using cached catalog (%.1f h old)", age_h)
            return json.loads(target.read_text(encoding="utf-8"))
    log.info("Downloading catalog: %s", CATALOG_URL)
    r = session.get(CATALOG_URL, timeout=90)
    r.raise_for_status()
    target.write_bytes(r.content)
    return r.json()


def flatten_catalog(nodes: list[dict], path: list[str] | None = None) -> list[dict]:
    """Return every leaf dataset with its category path."""
    path = path or []
    out: list[dict] = []
    for n in nodes:
        name = node_name(n, "en")
        children = n.get("children") or []
        if children:
            out.extend(flatten_catalog(children, path + [name]))
        else:
            out.append({
                "dataset_id": n.get("id"),
                "code": n.get("code"),
                "name_en": n.get("name_en"),
                "name_uz": n.get("name_uz"),
                "name_ru": n.get("name_ru"),
                "category_path": " > ".join(path),
                "top_category": path[0] if path else None,
                "period": n.get("period"),
                "updated_at": n.get("updated_at"),
                "status": n.get("status"),
                "source_url": DATA_URL.format(id=n.get("id")),
            })
    return out


def catalog_df(catalog: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(flatten_catalog(catalog))
    if not df.empty:
        df = df.dropna(subset=["dataset_id"]).drop_duplicates("dataset_id")
        df["dataset_id"] = df["dataset_id"].astype(int)
    return df


def search_catalog(df: pd.DataFrame, query: str) -> pd.DataFrame:
    q = query.lower()
    hay = (df[["name_en", "name_uz", "name_ru", "category_path", "code"]]
           .fillna("").astype(str).agg(" | ".join, axis=1).str.lower())
    return df[hay.str.contains(re.escape(q), regex=True)]


PRESET_EXCLUDE = ["telegraph", "postal", "telephone", "communication services rendered",
                  "cities with a population of 50", "share of women", "share of men",
                  "girls born", "boys born", "women who died", "men who died",
                  "30-year"]
DISTRICT_HINTS = ["district", "tuman", "район", "city and district", "shahar va tuman"]
REGION_HINTS = ["region", "hudud", "viloyat", "регион", "област", "by territor"]
ANNUAL_HINTS = ["yillik", "annual", "годов"]


def select_preset(df: pd.DataFrame, annual_only: bool = True) -> pd.DataFrame:
    """Pick business-relevant datasets and rank them so --max takes the most useful first.

    Ranking: district breakdown > regional breakdown > national; annual first; most recently updated first.
    Only dataset *names* are matched (not category paths) to avoid pulling whole categories.
    """
    names = df[["name_en", "name_uz", "name_ru"]].fillna("").astype(str).agg(" | ".join, axis=1).str.lower()
    path = df["category_path"].fillna("").str.lower()
    topics = pd.Series([None] * len(df), index=df.index, dtype=object)
    for topic, words in BUSINESS_PRESET.items():
        mask = names.apply(lambda h: any(w.lower() in h for w in words)) & topics.isna()
        topics[mask] = topic
    excluded = (names + " | " + path).apply(lambda h: any(x in h for x in PRESET_EXCLUDE))
    sel = df.assign(topic=topics)[topics.notna() & ~excluded].copy()
    if annual_only:
        per = sel["period"].fillna("").str.lower()
        sel = sel[per.apply(lambda p: any(a in p for a in ANNUAL_HINTS)) | (per == "")]
    n = names.loc[sel.index]
    sel["geo_rank"] = n.apply(lambda h: 2 if any(d in h for d in DISTRICT_HINTS)
                              else 1 if any(r in h for r in REGION_HINTS) else 0)
    sel = sel.sort_values(["geo_rank", "updated_at"], ascending=[False, False])
    return sel


# ---------------------------------------------------------------------------
# Dataset download
# ---------------------------------------------------------------------------

@dataclass
class FetchResult:
    dataset_id: int
    status: str            # ok | cached | failed
    http_status: int | None = None
    bytes: int = 0
    sha256: str | None = None
    error: str | None = None
    retrieved_at: str = field(default_factory=utcnow)


def fetch_dataset(session: requests.Session, paths: Paths, dataset_id: int,
                  updated_at: str | None, refresh: bool) -> FetchResult:
    raw_file = paths.raw_datasets / f"{dataset_id}.json"
    meta_file = paths.raw_datasets / f"{dataset_id}.meta.json"
    if raw_file.exists() and meta_file.exists() and not refresh:
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        if updated_at is None or meta.get("catalog_updated_at") == updated_at:
            return FetchResult(dataset_id, "cached", sha256=meta.get("sha256"),
                               bytes=raw_file.stat().st_size, retrieved_at=meta.get("retrieved_at", utcnow()))
    url = DATA_URL.format(id=dataset_id)
    try:
        r = session.get(url, timeout=120)
        if r.status_code != 200:
            return FetchResult(dataset_id, "failed", r.status_code, error=f"HTTP {r.status_code}")
        payload = r.content
        json.loads(payload)  # must be valid JSON before we store it
        digest = sha256(payload)
        raw_file.write_bytes(payload)
        res = FetchResult(dataset_id, "ok", 200, len(payload), digest)
        meta_file.write_text(json.dumps({
            "dataset_id": dataset_id, "source_url": url, "retrieved_at": res.retrieved_at,
            "sha256": digest, "bytes": len(payload), "catalog_updated_at": updated_at,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        return res
    except (requests.RequestException, ValueError) as e:
        return FetchResult(dataset_id, "failed", error=str(e)[:300])


def fetch_many(session: requests.Session, paths: Paths, rows: pd.DataFrame,
               workers: int, refresh: bool, delay: float) -> list[FetchResult]:
    results: list[FetchResult] = []
    updated = dict(zip(rows["dataset_id"], rows.get("updated_at", pd.Series([None] * len(rows)))))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {}
        for ds_id in rows["dataset_id"].astype(int):
            futs[ex.submit(fetch_dataset, session, paths, ds_id, updated.get(ds_id), refresh)] = ds_id
            time.sleep(delay)  # spread requests; SIAT is a public service
        for i, f in enumerate(as_completed(futs), 1):
            res = f.result()
            results.append(res)
            lvl = logging.WARNING if res.status == "failed" else logging.INFO
            log.log(lvl, "[%d/%d] dataset %s → %s %s", i, len(futs), res.dataset_id, res.status, res.error or "")
    return results


# ---------------------------------------------------------------------------
# Parsing & normalisation
# ---------------------------------------------------------------------------

def unwrap_payload(raw: Any) -> dict:
    obj = raw[0] if isinstance(raw, list) and raw else raw
    if not isinstance(obj, dict) or "data" not in obj:
        raise ValueError("Unexpected dataset format (no 'data' key)")
    obj.setdefault("metadata", [])
    return obj


def meta_lookup(metadata: list[dict], *needles: str) -> str | None:
    """Find a metadata value whose field name (any language) contains a needle."""
    for f in metadata:
        names = " | ".join(str(f.get(f"name_{l}") or "") for l in LANGS) + " | " + str(f.get("name") or "")
        names = names.lower()
        if any(n in names for n in needles):
            for l in ("en", "uz", "ru", "uzc"):
                v = f.get(f"value_{l}")
                if v not in (None, ""):
                    return str(v).strip()
            if f.get("value") not in (None, ""):
                return str(f["value"]).strip()
    return None


def parse_number(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return None if v != v else float(v)  # NaN check
    s = str(v).strip().lower().replace("\u00a0", "").replace(" ", "")
    if s in MISSING_TOKENS:
        return None
    s = s.lstrip("*").rstrip("*")
    if s.count(",") == 1 and s.count(".") == 0:
        s = s.replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def parse_period(key: str) -> dict | None:
    k = str(key).strip()
    for pat, kind in PERIOD_PATTERNS:
        m = pat.match(k)
        if not m:
            continue
        if kind == "A":
            return {"freq": "A", "year": int(m.group(1)), "quarter": None, "month": None}
        if kind == "Q":
            q = m.group(2).upper()
            q = ROMAN.get(q, None) if not q.isdigit() else int(q)
            return {"freq": "Q", "year": int(m.group(1)), "quarter": q, "month": None}
        if kind == "M":
            mo = int(m.group(2))
            if 1 <= mo <= 12:
                return {"freq": "M", "year": int(m.group(1)), "quarter": (mo - 1) // 3 + 1, "month": mo}
        if kind == "M_rev":
            mo = int(m.group(1))
            if 1 <= mo <= 12:
                return {"freq": "M", "year": int(m.group(2)), "quarter": (mo - 1) // 3 + 1, "month": mo}
        if kind == "YTD":
            return {"freq": "YTD", "year": int(m.group(1)), "quarter": None, "month": None}
    return None


def is_label_key(k: str) -> bool:
    return k in LABEL_KEYS_EXACT or k.startswith(LABEL_KEY_PREFIXES)


def classify_territory(code: str, name: str) -> tuple[str, str | None]:
    """Return (level, region_soato) from a SOATO-like code, falling back to the name."""
    c = re.sub(r"\D", "", str(code or ""))
    if c:
        if c in ("17", "1700", "1700000"):
            return "country", None
        if len(c) == 4:
            return ("region", c) if c in REGION_CODES else ("other", None)
        if len(c) >= 7 and c[:4] in REGION_CODES:
            return "district", c[:4]
    n = (name or "").lower()
    if any(a == n.strip() or a in n for a in COUNTRY_ALIASES) and not any(
            any(al in n for al in r["aliases"]) for r in REGIONS):
        return "country", None
    for r in REGIONS:
        if any(al in n for al in r["aliases"]):
            # "Fergana region" vs "Fergana city" — city/district rows usually carry a 7-digit code;
            # without a code we treat a region-name match as region-level.
            return "region", r["soato"]
    return "other", None


def normalise_dataset(dataset_id: int, raw: Any, cat_row: dict | None, fetch_meta: dict) -> tuple[dict, list[dict], dict]:
    """Return (indicator_row, observation_rows, quality_report)."""
    obj = unwrap_payload(raw)
    metadata: list[dict] = obj.get("metadata") or []
    data: list[dict] = obj.get("data") or []
    cat_row = cat_row or {}

    name_en = meta_lookup(metadata, "indicator name", "наименование показателя", "ko'rsatkich nomi") \
        or cat_row.get("name_en")
    unit = meta_lookup(metadata, "unit", "единица", "o'lchov birligi", "oʻlchov")
    periodicity = meta_lookup(metadata, "periodicity", "периодичн", "davriylik")
    source_org = meta_lookup(metadata, "source", "источник", "manba")
    methodology = meta_lookup(metadata, "methodolog", "методолог", "metodologiya")

    indicator = {
        "dataset_id": dataset_id,
        "indicator_code": f"siat_{dataset_id}",
        "siat_code": cat_row.get("code"),
        "name_en": name_en,
        "name_uz": cat_row.get("name_uz"),
        "name_ru": cat_row.get("name_ru"),
        "category_path": cat_row.get("category_path"),
        "topic": cat_row.get("topic"),
        "unit": unit,
        "periodicity": periodicity,
        "source_org": source_org,
        "methodology": methodology,
        "catalog_updated_at": cat_row.get("updated_at"),
        "source": SOURCE_NAME,
        "source_url": DATA_URL.format(id=dataset_id),
        "retrieved_at": fetch_meta.get("retrieved_at"),
        "raw_sha256": fetch_meta.get("sha256"),
        "metadata_json": json.dumps(metadata, ensure_ascii=False),
    }

    obs: list[dict] = []
    q = {"dataset_id": dataset_id, "rows_in": len(data), "values_total": 0, "values_ok": 0,
         "values_missing": 0, "values_unparseable": 0, "unknown_period_keys": set(),
         "levels": {}, "duplicates": 0, "negative_values": 0, "checks": {}}

    for row in data:
        code = str(row.get("Code") or row.get("code") or "").strip()
        label_en = row.get("Klassifikator_en") or row.get("Klassifikator") or ""
        label_uz = row.get("Klassifikator") or ""
        label_ru = row.get("Klassifikator_ru") or ""
        level, region_soato = classify_territory(code, " ".join([str(label_en), str(label_uz), str(label_ru)]))
        q["levels"][level] = q["levels"].get(level, 0) + 1

        # Extra label columns (e.g. sex, age group, sector) → dimensions
        dims = {k: v for k, v in row.items()
                if is_label_key(k) is False and parse_period(k) is None and not isinstance(v, (int, float))
                and parse_number(v) is None and v not in (None, "")}

        for k, v in row.items():
            if is_label_key(k) or k in dims:
                continue
            per = parse_period(k)
            if per is None:
                q["unknown_period_keys"].add(k)
                continue
            q["values_total"] += 1
            val = parse_number(v)
            if val is None:
                if v is None or str(v).strip().lower() in MISSING_TOKENS:
                    q["values_missing"] += 1
                else:
                    q["values_unparseable"] += 1
                continue
            q["values_ok"] += 1
            if val < 0:
                q["negative_values"] += 1
            obs.append({
                "dataset_id": dataset_id,
                "indicator_code": indicator["indicator_code"],
                "level": level,
                "soato_code": code or None,
                "region_soato": region_soato,
                "territory_en": str(label_en).strip() or None,
                "territory_uz": str(label_uz).strip() or None,
                "territory_ru": str(label_ru).strip() or None,
                "dimensions": json.dumps(dims, ensure_ascii=False) if dims else None,
                "period_label": str(k),
                "freq": per["freq"],
                "year": per["year"],
                "quarter": per["quarter"],
                "month": per["month"],
                "value": val,
                "unit": unit,
                "source": SOURCE_NAME,
                "source_url": indicator["source_url"],
                "retrieved_at": indicator["retrieved_at"],
                "is_synthetic": False,
            })

    # --- validation checks (report only; nothing is modified) ---
    if obs:
        df = pd.DataFrame(obs)
        key = ["level", "soato_code", "territory_en", "dimensions", "period_label"]
        dup = df.duplicated(subset=key, keep=False)
        q["duplicates"] = int(dup.sum())
        q["checks"]["has_regional_breakdown"] = bool((df["level"] == "region").any())
        q["checks"]["has_district_breakdown"] = bool((df["level"] == "district").any())
        q["checks"]["regions_covered"] = int(df.loc[df["level"] == "region", "region_soato"].nunique())
        q["checks"]["year_min"] = int(df["year"].min())
        q["checks"]["year_max"] = int(df["year"].max())
        q["checks"]["unit_known"] = unit is not None
        # Regions should approximately add up to the country total for additive indicators.
        q["checks"]["region_sum_vs_country"] = region_sum_check(df, unit)
    q["unknown_period_keys"] = sorted(q["unknown_period_keys"])[:20]
    q["missing_ratio"] = round(q["values_missing"] / q["values_total"], 4) if q["values_total"] else None
    q["passed"] = bool(obs) and q["values_unparseable"] == 0 and q["duplicates"] == 0
    return indicator, obs, q


ADDITIVE_UNIT_HINTS = ("person", "people", "чел", "kishi", "thousand", "тыс", "ming", "bln", "mln", "млрд", "млн",
                       "mlrd", "units", "единиц", "dona", "soum", "сум", "so'm")
NON_ADDITIVE_HINTS = ("%", "percent", "процент", "foiz", "per ", "на 1", "index", "индекс", "indeks", "average",
                      "средн", "o'rtacha")


def region_sum_check(df: pd.DataFrame, unit: str | None) -> dict | None:
    u = (unit or "").lower()
    if not u or any(h in u for h in NON_ADDITIVE_HINTS) or not any(h in u for h in ADDITIVE_UNIT_HINTS):
        return None
    sub = df[df["dimensions"].isna()]
    if sub.loc[sub["level"] == "region", "region_soato"].nunique() < len(REGION_CODES):
        return None  # only meaningful when all 14 regions are present
    country = sub[sub["level"] == "country"].groupby("period_label")["value"].sum()
    regions = sub[sub["level"] == "region"].groupby("period_label")["value"].sum()
    common = country.index.intersection(regions.index)
    if common.empty:
        return None
    rel = ((regions[common] - country[common]).abs() / country[common].replace(0, pd.NA)).dropna()
    if rel.empty:
        return None
    return {"max_rel_diff": round(float(rel.max()), 4), "ok": bool(rel.max() <= 0.02)}


# ---------------------------------------------------------------------------
# Build processed tables
# ---------------------------------------------------------------------------

def build(paths: Paths, cat: pd.DataFrame, dataset_ids: Iterable[int], fetch_log: list[FetchResult]) -> dict:
    cat_by_id = {int(r["dataset_id"]): r for r in cat.to_dict("records")} if not cat.empty else {}
    indicators, observations, quality = [], [], []
    for ds_id in sorted(set(int(i) for i in dataset_ids)):
        raw_file = paths.raw_datasets / f"{ds_id}.json"
        meta_file = paths.raw_datasets / f"{ds_id}.meta.json"
        if not raw_file.exists():
            continue
        fetch_meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
        try:
            raw = json.loads(raw_file.read_text(encoding="utf-8"))
            ind, obs, q = normalise_dataset(ds_id, raw, cat_by_id.get(ds_id), fetch_meta)
        except Exception as e:  # keep going; record failure
            log.warning("Parse failed for dataset %s: %s", ds_id, e)
            quality.append({"dataset_id": ds_id, "passed": False, "error": str(e)[:300]})
            continue
        indicators.append(ind)
        observations.extend(obs)
        quality.append(q)

    ind_df = pd.DataFrame(indicators)
    obs_df = pd.DataFrame(observations)
    reg_df = pd.DataFrame([{k: v for k, v in r.items() if k != "aliases"} for r in REGIONS])
    log_df = pd.DataFrame([r.__dict__ for r in fetch_log])

    ind_df.to_csv(paths.processed / "indicators.csv", index=False)
    obs_df.to_csv(paths.processed / "observations.csv", index=False)
    reg_df.to_csv(paths.processed / "regions.csv", index=False)
    if not cat.empty:
        cat.to_csv(paths.processed / "catalog.csv", index=False)
    if not log_df.empty:
        log_path = paths.processed / "ingestion_log.csv"
        log_df.to_csv(log_path, mode="a", header=not log_path.exists(), index=False)
    try:
        obs_df.to_parquet(paths.processed / "observations.parquet", index=False)
    except Exception:
        pass  # pyarrow not installed — CSV is enough

    report = {
        "generated_at": utcnow(),
        "datasets_parsed": len(indicators),
        "observations": len(obs_df),
        "datasets_with_regions": int(sum(1 for q in quality if q.get("checks", {}).get("has_regional_breakdown"))),
        "datasets_with_districts": int(sum(1 for q in quality if q.get("checks", {}).get("has_district_breakdown"))),
        "datasets_failed_checks": [q["dataset_id"] for q in quality if not q.get("passed")],
        "per_dataset": quality,
    }
    (paths.processed / "quality_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=list), encoding="utf-8")

    write_sqlite(paths.sqlite, {"catalog": cat, "indicators": ind_df, "observations": obs_df,
                                "regions": reg_df, "ingestion_log": log_df})
    return report


def write_sqlite(db_path: Path, tables: dict[str, pd.DataFrame]) -> None:
    with sqlite3.connect(db_path) as con:
        for name, df in tables.items():
            if df is None or df.empty:
                continue
            mode = "append" if name == "ingestion_log" else "replace"
            df.to_sql(name, con, if_exists=mode, index=False)
        con.executescript("""
            CREATE INDEX IF NOT EXISTS ix_obs_ind ON observations(indicator_code);
            CREATE INDEX IF NOT EXISTS ix_obs_geo ON observations(level, region_soato, soato_code);
            CREATE INDEX IF NOT EXISTS ix_obs_year ON observations(year);
        """) if "observations" in tables and not tables["observations"].empty else None


def write_postgres(url: str, paths: Paths) -> None:
    from sqlalchemy import create_engine  # optional dependency
    eng = create_engine(url)
    for name in ("catalog", "indicators", "observations", "regions"):
        f = paths.processed / f"{name}.csv"
        if f.exists() and f.stat().st_size > 1:
            df = pd.read_csv(f)
            df.to_sql(f"siat_{name}", eng, if_exists="replace", index=False, chunksize=5000, method="multi")
            log.info("PostgreSQL: wrote %s rows to siat_%s", len(df), name)


# ---------------------------------------------------------------------------
# Self-test (offline)
# ---------------------------------------------------------------------------

SAMPLE_PAYLOAD = [{
    "metadata": [
        {"name_en": "Indicator name", "value_en": "Resident population (annual average)"},
        {"name_en": "Unit of measurement", "value_en": "thousand persons"},
        {"name_en": "Periodicity", "value_en": "Annual"},
        {"name_en": "Source", "value_en": "Statistics Agency"},
    ],
    "data": [
        {"Code": "1700", "Klassifikator": "O'zbekiston Respublikasi", "Klassifikator_en": "Republic of Uzbekistan",
         "2022": "35,648.1", "2023": 36361.3, "2024": "37 125,0"},
        {"Code": "1730", "Klassifikator": "Farg'ona viloyati", "Klassifikator_en": "Fergana region",
         "2022": 3943.0, "2023": "4013.6", "2024": "-"},
        {"Code": "1730212", "Klassifikator": "Quva tumani", "Klassifikator_en": "Kuva district",
         "2022": 230.4, "2023": 234.1, "2024": "…"},
        {"Code": "", "Klassifikator_en": "Andijan region", "2022": 3285.1, "2023": "3348,9", "2024": "abc"},
        {"Code": "1726", "Klassifikator_en": "Tashkent city", "2022-II": 2955.0, "2023-01": 2960.1},
    ],
}]


def selftest() -> int:
    ind, obs, q = normalise_dataset(999, SAMPLE_PAYLOAD, {"name_uz": "Aholi"}, {"retrieved_at": utcnow()})
    df = pd.DataFrame(obs)
    print(df[["level", "soato_code", "region_soato", "territory_en", "period_label", "freq", "year",
              "quarter", "month", "value"]].to_string(index=False))
    print("\nindicator:", {k: ind[k] for k in ("name_en", "unit", "periodicity", "source_org")})
    print("quality:", {k: q[k] for k in ("values_total", "values_ok", "values_missing", "values_unparseable",
                                          "levels", "passed")})
    checks = [
        (ind["unit"] == "thousand persons", "unit parsed"),
        (df.query("soato_code=='1700' and year==2022")["value"].iloc[0] == 35648.1, "thousands separator"),
        (df.query("soato_code=='1700' and year==2024")["value"].iloc[0] == 37125.0, "space + decimal comma"),
        (df.query("soato_code=='1730212'")["level"].iloc[0] == "district", "district from 7-digit code"),
        (df.query("territory_en=='Andijan region'")["region_soato"].iloc[0] == "1703", "region from name"),
        (q["values_missing"] == 2 and q["values_unparseable"] == 1, "missing vs unparseable"),
        (set(df.query("soato_code=='1726'")["freq"]) == {"Q", "M"}, "quarter/month periods"),
    ]
    ok = all(c for c, _ in checks)
    for c, name in checks:
        print(("PASS " if c else "FAIL ") + name)
    return 0 if ok else 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Download and structure SIAT (siat.stat.uz) statistics.")
    p.add_argument("--out", default="data", help="output directory (default: ./data)")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("catalog", help="download the catalog and write processed/catalog.csv")
    s.add_argument("--refresh", action="store_true")

    s = sub.add_parser("search", help="search the catalog")
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=40)

    s = sub.add_parser("fetch", help="download datasets and build structured tables")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--ids", type=int, nargs="+")
    g.add_argument("--query")
    g.add_argument("--preset", choices=["business"])
    g.add_argument("--all", action="store_true")
    s.add_argument("--max", type=int, default=None, help="cap the number of datasets")
    s.add_argument("--per-topic", type=int, default=None,
                   help="with --preset: take the top N datasets of each topic (balanced coverage)")
    s.add_argument("--all-periods", action="store_true",
                   help="with --preset: include quarterly/monthly datasets (default: annual only)")
    s.add_argument("--workers", type=int, default=4)
    s.add_argument("--delay", type=float, default=0.25, help="seconds between request submissions")
    s.add_argument("--refresh", action="store_true", help="re-download even if cached")
    s.add_argument("--database-url", help="also write tables to PostgreSQL (SQLAlchemy URL)")

    s = sub.add_parser("rebuild", help="re-parse all raw files without network access")
    s.add_argument("--database-url")

    sub.add_parser("selftest", help="offline parser test")
    sub.add_parser("report", help="show which downloaded datasets have region/district data")

    a = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")

    if a.cmd == "selftest":
        return selftest()

    paths = Paths(Path(a.out))
    paths.ensure()

    if a.cmd == "report":
        return show_report(paths)

    if a.cmd == "rebuild":
        cat_file = paths.processed / "catalog.csv"
        cat = pd.read_csv(cat_file) if cat_file.exists() else pd.DataFrame()
        ids = [int(f.stem) for f in paths.raw_datasets.glob("*.json") if f.stem.isdigit()]
        report = build(paths, cat, ids, [])
        if a.database_url:
            write_postgres(a.database_url, paths)
        print_summary(report, paths)
        return 0

    session = make_session()
    try:
        cat = catalog_df(download_catalog(session, paths, refresh=getattr(a, "refresh", False)))
    except requests.RequestException as e:
        log.error("Cannot reach SIAT catalog (%s). Check your network / VPN and try again.", e)
        return 2
    cat.to_csv(paths.processed / "catalog.csv", index=False)

    if a.cmd == "catalog":
        print(f"{len(cat)} datasets in catalog → {paths.processed / 'catalog.csv'}")
        print(cat.groupby("top_category").size().sort_values(ascending=False).to_string())
        return 0

    if a.cmd == "search":
        res = search_catalog(cat, a.query)
        pd.set_option("display.width", 200)
        print(res[["dataset_id", "name_en", "category_path", "period", "updated_at"]]
              .head(a.limit).to_string(index=False))
        print(f"\n{len(res)} match(es).")
        return 0

    # fetch
    if a.ids:
        sel = cat[cat["dataset_id"].isin(a.ids)]
        missing = set(a.ids) - set(sel["dataset_id"])
        if missing:  # allow ids not present in catalog
            sel = pd.concat([sel, pd.DataFrame({"dataset_id": sorted(missing)})], ignore_index=True)
    elif a.query:
        sel = search_catalog(cat, a.query)
    elif a.preset:
        sel = select_preset(cat, annual_only=not a.all_periods)
        if a.per_topic:
            sel = sel.groupby("topic", group_keys=False).head(a.per_topic)
        log.info("Preset 'business' selected %d datasets: %s", len(sel),
                 sel["topic"].value_counts().to_dict())
    else:
        sel = cat
    if a.max:
        sel = sel.head(a.max)
    if sel.empty:
        log.error("Nothing selected.")
        return 1

    cat = cat.merge(sel[["dataset_id", "topic"]], on="dataset_id", how="left") if "topic" in sel else cat
    results = fetch_many(session, paths, sel, a.workers, a.refresh, a.delay)
    # Rebuild from every raw dataset on disk so earlier downloads are kept in processed tables.
    all_ids = [int(f.stem) for f in paths.raw_datasets.glob("*.json") if f.stem.isdigit()]
    report = build(paths, cat, all_ids, results)
    if a.database_url:
        write_postgres(a.database_url, paths)
    failed = [r.dataset_id for r in results if r.status == "failed"]
    if failed:
        log.warning("%d dataset(s) failed to download: %s", len(failed), failed[:30])
    print_summary(report, paths)
    return 0


def show_report(paths: Paths) -> int:
    ind_f, obs_f = paths.processed / "indicators.csv", paths.processed / "observations.csv"
    if not obs_f.exists():
        print("No processed data yet. Run `fetch` first.")
        return 1
    obs = pd.read_csv(obs_f, usecols=["dataset_id", "level", "region_soato", "year"])
    ind = pd.read_csv(ind_f, usecols=["dataset_id", "name_en", "unit", "topic"])
    g = obs.groupby("dataset_id").agg(
        rows=("level", "size"),
        regions=("region_soato", "nunique"),
        districts=("level", lambda s: int((s == "district").sum())),
        other=("level", lambda s: int((s == "other").sum())),
        year_min=("year", "min"), year_max=("year", "max")).reset_index()
    t = ind.merge(g, on="dataset_id", how="left").sort_values(["districts", "regions"], ascending=False)
    pd.set_option("display.width", 220)
    pd.set_option("display.max_colwidth", 70)
    print(t.to_string(index=False))
    print(f"\nlevels overall: {obs['level'].value_counts().to_dict()}")
    q = json.loads((paths.processed / "quality_report.json").read_text(encoding="utf-8"))
    unk = {d["dataset_id"]: d.get("unknown_period_keys") for d in q["per_dataset"] if d.get("unknown_period_keys")}
    if unk:
        print("unrecognised period columns (check these):", unk)
    if (obs["level"] == "other").any():
        print("rows with level='other' have codes/names not matched to SOATO — inspect observations.csv")
    return 0


def print_summary(report: dict, paths: Paths) -> None:
    print("\n=== SIAT ingestion summary ===")
    print(f"datasets parsed        : {report['datasets_parsed']}")
    print(f"observations           : {report['observations']}")
    print(f"with regional breakdown: {report['datasets_with_regions']}")
    print(f"with district breakdown: {report['datasets_with_districts']}")
    print(f"failed quality checks  : {len(report['datasets_failed_checks'])}")
    print(f"outputs                : {paths.processed}/ and {paths.sqlite}")


if __name__ == "__main__":
    sys.exit(main())
