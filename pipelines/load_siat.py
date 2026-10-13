#!/usr/bin/env python3
"""Load SIAT processed tables (from pipelines/siat_ingest.py) into the PostgreSQL warehouse.

    python pipelines/load_siat.py [--data data] [--map data/reference/indicator_map.yaml]

- keeps only datasets listed in indicator_map.yaml and maps them to internal indicator codes
- converts units once (unit_multiplier): thousand people → persons, bln UZS → UZS
- builds regions (14) and districts (from SIAT dataset 307: 1 = district, 0 = city)
- idempotent upsert: running it twice changes nothing
- records the run in ingestion_runs
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import yaml
from pydantic import BaseModel, Field
from sqlalchemy import Connection, select
from sqlalchemy.dialects.postgresql import insert

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.db.models import DataSource, District, Indicator, IngestionRun, Observation, Region  # noqa: E402
from app.db.session import get_engine  # noqa: E402

SOURCE_NAME = "siat"
MAX_PARAMS = 60000  # PostgreSQL allows at most 65535 bind parameters per statement


# --- indicator map -------------------------------------------------------------


class IndicatorSpec(BaseModel):
    siat_dataset_id: int
    name_en: str
    category: str
    source_unit: str
    unit: str
    unit_multiplier: float = Field(gt=0)
    frequency: str = "annual"
    additive: bool
    higher_is_better: bool = True


class IndicatorMap(BaseModel):
    indicators: dict[str, IndicatorSpec]
    reference: dict[str, dict[str, int]] = {}


def load_map(path: Path) -> IndicatorMap:
    m = IndicatorMap.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    ids = [s.siat_dataset_id for s in m.indicators.values()]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"SIAT dataset mapped twice in {path}: {sorted(dupes)}")
    return m


# --- transforms (pure, unit-tested) ----------------------------------------------


def district_kind(value: float | None, name_en: str | None) -> str:
    """Dataset 307: 1 = district, 0 = city. Names ending in 'city' are cities regardless of the value."""
    if name_en and "city" in name_en.lower():
        return "city"
    return "city" if value == 0 else "district"


def convert_values(obs: pd.DataFrame, spec_by_dataset: dict[int, tuple[str, IndicatorSpec]]) -> pd.DataFrame:
    """Keep mapped datasets, attach internal codes, convert units. Never touches non-mapped rows."""
    out = obs[obs["dataset_id"].isin(spec_by_dataset) & obs["level"].isin(["country", "region", "district"])].copy()
    out["indicator_code"] = out["dataset_id"].map(lambda d: spec_by_dataset[d][0])
    out["value"] = out["value"] * out["dataset_id"].map(lambda d: spec_by_dataset[d][1].unit_multiplier)
    out["unit"] = out["dataset_id"].map(lambda d: spec_by_dataset[d][1].unit)
    return out


# --- loading ---------------------------------------------------------------------


def upsert(conn: Connection, model: type, rows: list[dict], key: list[str]) -> None:
    if not rows:
        return
    table = model.__table__
    chunk = max(1, MAX_PARAMS // len(rows[0]))
    for i in range(0, len(rows), chunk):
        stmt = insert(table).values(rows[i : i + chunk])
        skip = {*key, "id", "ingested_at"}
        # Only overwrite the columns this loader provides: columns owned by other pipelines
        # (e.g. centroids / geom_approx from load_reference.py) must survive a reload.
        update_cols = {c: stmt.excluded[c] for c in rows[0] if c not in skip}
        conn.execute(stmt.on_conflict_do_update(index_elements=key, set_=update_cols))


def first_names(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df.sort_values("year", ascending=False)
        .drop_duplicates("soato_code")[["soato_code", "region_soato", "territory_en", "territory_uz", "territory_ru"]]
        .set_index("soato_code")
    )


def clean(v: object) -> str | None:
    return None if pd.isna(v) else str(v).strip()


def nn(v: object) -> object:
    return None if pd.isna(v) else v


def load(data_dir: Path, map_path: Path) -> dict:
    imap = load_map(map_path)
    spec_by_dataset = {s.siat_dataset_id: (code, s) for code, s in imap.indicators.items()}
    district_ref = imap.reference.get("district_kind", {}).get("siat_dataset_id", 307)

    processed = data_dir / "processed"
    obs = pd.read_csv(processed / "observations.csv", dtype={"soato_code": str, "region_soato": str}, low_memory=False)
    ind = pd.read_csv(processed / "indicators.csv")
    meta = ind.set_index("dataset_id")

    missing = sorted(set(spec_by_dataset) - set(obs["dataset_id"].unique()))
    if missing:
        print(f"WARNING: mapped datasets not downloaded yet: {missing} — run siat_ingest.py fetch --ids ...")

    started = datetime.now(UTC)
    engine = get_engine()
    with engine.begin() as conn:
        retrieved = pd.to_datetime(obs["retrieved_at"]).max()
        upsert(
            conn,
            DataSource,
            [
                {
                    "name": SOURCE_NAME,
                    "url": "https://siat.stat.uz",
                    "kind": "siat",
                    "license": "Official statistics of the Republic of Uzbekistan (stat.uz)",
                    "retrieved_at": retrieved.to_pydatetime(),
                }
            ],
            ["name"],
        )
        source_id = conn.execute(select(DataSource.id).where(DataSource.name == SOURCE_NAME)).scalar_one()

        # Regions: names from the population dataset (most complete), codes from the SOATO reference.
        pop_ds = imap.indicators["population_total"].siat_dataset_id
        reg_names = first_names(obs[(obs["dataset_id"] == pop_ds) & (obs["level"] == "region")])
        regions_ref = pd.read_csv(processed / "regions.csv", dtype={"soato": str})
        region_rows = []
        for r in regions_ref.itertuples():
            n = reg_names.loc[r.soato] if r.soato in reg_names.index else None
            region_rows.append(
                {
                    "soato_code": r.soato,
                    "name_en": clean(n["territory_en"]) if n is not None else r.name_en,
                    "name_uz": clean(n["territory_uz"]) if n is not None else r.name_uz,
                    "name_ru": clean(n["territory_ru"]) if n is not None else None,
                }
            )
        upsert(conn, Region, region_rows, ["soato_code"])
        region_id = dict(conn.execute(select(Region.soato_code, Region.id)).all())

        # Districts: every district-level code seen in mapped datasets; kind from the reference dataset.
        dist_obs = obs[(obs["level"] == "district") & obs["dataset_id"].isin([*spec_by_dataset, district_ref])]
        names = first_names(dist_obs)
        ref = obs[(obs["dataset_id"] == district_ref) & (obs["level"] == "district")]
        kind_value = ref.sort_values("year").groupby("soato_code")["value"].last().to_dict()
        district_rows = [
            {
                "soato_code": code,
                "region_id": region_id[row.region_soato],
                "name_en": clean(row.territory_en) or code,
                "name_uz": clean(row.territory_uz),
                "name_ru": clean(row.territory_ru),
                "kind": district_kind(kind_value.get(code), clean(row.territory_en)),
            }
            for code, row in names.iterrows()
            if row.region_soato in region_id
        ]
        upsert(conn, District, district_rows, ["soato_code"])
        district_id = dict(conn.execute(select(District.soato_code, District.id)).all())

        upsert(
            conn,
            Indicator,
            [
                {
                    "code": code,
                    "name_en": s.name_en,
                    "category": s.category,
                    "unit": s.unit,
                    "source_unit": s.source_unit,
                    "unit_multiplier": s.unit_multiplier,
                    "frequency": s.frequency,
                    "additive": s.additive,
                    "higher_is_better": s.higher_is_better,
                    "siat_dataset_id": s.siat_dataset_id,
                    "source_name": clean(meta.loc[s.siat_dataset_id, "name_en"])
                    if s.siat_dataset_id in meta.index
                    else None,
                }
                for code, s in imap.indicators.items()
            ],
            ["code"],
        )
        indicator_id = dict(conn.execute(select(Indicator.code, Indicator.id)).all())

        conv = convert_values(obs, spec_by_dataset)
        sha = meta["raw_sha256"].to_dict() if "raw_sha256" in meta else {}
        rows, rejected = [], 0
        for r in conv.itertuples(index=False):
            if r.level == "district":
                did = district_id.get(r.soato_code)
                rid = region_id.get(r.region_soato)
                if did is None:
                    rejected += 1
                    continue
            elif r.level == "region":
                did, rid = None, region_id.get(r.region_soato)
                if rid is None:
                    rejected += 1
                    continue
            else:
                did, rid = None, None
            rows.append(
                {
                    "indicator_id": indicator_id[r.indicator_code],
                    "level": r.level,
                    "region_id": rid,
                    "district_id": did,
                    "year": int(r.year),
                    "quarter": None if pd.isna(r.quarter) else int(r.quarter),
                    "month": None if pd.isna(r.month) else int(r.month),
                    "period_label": str(r.period_label),
                    "value": float(r.value),
                    "unit": r.unit,
                    "source_id": source_id,
                    "source_url": r.source_url,
                    "retrieved_at": pd.Timestamp(r.retrieved_at).to_pydatetime(),
                    "raw_sha256": nn(sha.get(r.dataset_id)),
                    "is_synthetic": False,
                }
            )
        upsert(
            conn,
            Observation,
            rows,
            ["indicator_id", "level", "region_id", "district_id", "year", "quarter", "month", "source_id"],
        )

        summary = {
            "regions": len(region_rows),
            "districts": len(district_rows),
            "cities": sum(d["kind"] == "city" for d in district_rows),
            "indicators": len(imap.indicators),
            "rows_in": len(conv),
            "rows_loaded": len(rows),
            "rows_rejected": rejected,
        }
        conn.execute(
            insert(IngestionRun).values(
                source_id=source_id,
                started_at=started,
                finished_at=datetime.now(UTC),
                status="ok",
                datasets_ok=int(conv["dataset_id"].nunique()),
                rows_in=len(conv),
                rows_loaded=len(rows),
                rows_rejected=rejected,
            )
        )
    return summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--data", default=str(ROOT / "data"))
    p.add_argument("--map", default=str(ROOT / "data" / "reference" / "indicator_map.yaml"))
    a = p.parse_args(argv)
    summary = load(Path(a.data), Path(a.map))
    print("=== load_siat summary ===")
    for k, v in summary.items():
        print(f"{k:14}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
