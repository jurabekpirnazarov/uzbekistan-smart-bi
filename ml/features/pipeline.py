"""Compute every feature in definitions.yaml and write the `features` table (PLAN.md Phase 3).

Usage:  python -m ml.features.pipeline            (or: python manage.py features --local)

Rules: missing inputs → NaN + quality_flag (never imputed); any synthetic input → is_synthetic;
lineage = observation ids used; feature_version = hash of definitions.yaml.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.db.models import District, Feature, Indicator, Observation  # noqa: E402
from ml.features.registry import FEATURE_TYPES, NONE_ID, Panel, input_codes  # noqa: E402

DEFINITIONS = Path(__file__).with_name("definitions.yaml")
BATCH = 5000


def load_definitions(path: Path = DEFINITIONS) -> dict[str, dict]:
    defs = yaml.safe_load(path.read_text(encoding="utf-8"))
    for name, spec in defs.items():
        if spec.get("type") not in FEATURE_TYPES:
            raise ValueError(f"feature {name}: unknown type {spec.get('type')}")
    return defs


def feature_version(path: Path = DEFINITIONS) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:8]


def load_panel(db: Session) -> Panel:
    rows = db.execute(
        select(
            Observation.level,
            Observation.region_id,
            Observation.district_id,
            Observation.year,
            Indicator.code,
            Observation.value,
            Observation.id,
            Observation.is_synthetic,
        )
        .join(Indicator, Indicator.id == Observation.indicator_id)
        .where(Observation.quarter.is_(None), Observation.month.is_(None))
    ).all()
    obs = pd.DataFrame(
        rows,
        columns=["level", "region_id", "district_id", "year", "indicator", "value", "obs_id", "is_synthetic"],
    )
    kinds = dict(db.execute(select(District.id, District.kind)).all())
    return Panel(obs, kinds)


def compute_features(panel: Panel, defs: dict[str, dict]) -> pd.DataFrame:
    """Long frame: name, level, region_id, district_id, year, value, is_synthetic, quality_flag, lineage."""
    frames = []
    for name, spec in defs.items():
        res = FEATURE_TYPES[spec["type"]](panel, spec)
        vals = res.values.astype(float)
        any_input = (
            pd.concat([c.values.notna() for c in res.inputs], axis=1).any(axis=1) if res.inputs else vals.notna()
        )
        all_inputs = (
            pd.concat([c.values.notna() for c in res.inputs], axis=1).all(axis=1) if res.inputs else vals.notna()
        )
        synthetic = (
            pd.concat([c.synthetic for c in res.inputs], axis=1).any(axis=1)
            if res.inputs
            else pd.Series(False, index=vals.index)
        )
        keep = vals.notna() | any_input  # rows where the feature exists or is partially computable
        if not keep.any():
            continue
        flag = np.where(vals.notna(), None, np.where(all_inputs, "invalid_math", "missing_input"))
        ids = pd.concat([c.ids for c in res.inputs], axis=1) if res.inputs else None
        lineage = [
            {"observation_ids": [int(x) for x in row if pd.notna(x)]} if ids is not None else None
            for row in (ids.to_numpy() if ids is not None else [None] * len(vals))
        ]
        idx = vals.index.to_frame(index=False)
        df = idx.assign(
            name=name,
            value=vals.to_numpy(),
            is_synthetic=synthetic.to_numpy(),
            quality_flag=flag,
            lineage=lineage,
        )
        frames.append(df[keep.to_numpy()])
    out = pd.concat(frames, ignore_index=True)
    out["value"] = out["value"].astype(object).where(out["value"].notna(), None)
    return out


def write_features(db: Session, df: pd.DataFrame, version: str) -> int:
    db.execute(delete(Feature).where(Feature.feature_version != "forecast"))  # forecasts: ml.forecasting.train
    rows = [
        {
            "name": r.name,
            "level": r.level,
            "region_id": None if r.region_id == NONE_ID else int(r.region_id),
            "district_id": None if r.district_id == NONE_ID else int(r.district_id),
            "year": int(r.year),
            "value": r.value,
            "is_synthetic": bool(r.is_synthetic),
            "quality_flag": r.quality_flag,
            "lineage": r.lineage,
            "feature_version": version,
        }
        for r in df.itertuples(index=False)
    ]
    for i in range(0, len(rows), BATCH):
        db.execute(insert(Feature), rows[i : i + BATCH])
    db.commit()
    return len(rows)


def coverage_table(df: pd.DataFrame, defs: dict[str, dict], available: set[str]) -> str:
    ok = df[df["value"].notna()]
    lines = [f"{'feature':32} {'country':>14} {'region':>14} {'district':>14}"]
    for name, spec in defs.items():
        cells = []
        for lv in ("country", "region", "district"):
            sub = ok[(ok["name"] == name) & (ok["level"] == lv)]
            cells.append(f"{sub.year.min()}–{sub.year.max()}" if len(sub) else "—")
        missing = [c for c in input_codes(spec) if c not in available]
        note = f"  (missing input: {', '.join(missing)})" if missing else ""
        lines.append(f"{name:32} {cells[0]:>14} {cells[1]:>14} {cells[2]:>14}{note}")
    return "\n".join(lines)


def main() -> None:
    from app.db.session import get_sessionmaker

    defs = load_definitions()
    version = feature_version()
    with get_sessionmaker()() as db:
        panel = load_panel(db)
        df = compute_features(panel, defs)
        n = write_features(db, df, version)
    print(f"features: {n} rows written (feature_version {version})\n")
    print(coverage_table(df, defs, panel.indicators))


if __name__ == "__main__":
    main()
