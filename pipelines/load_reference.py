"""Load region / district geometry into the warehouse (PLAN.md Phase 2).

Sources (see data/reference/LICENSES.md):
- regions:   dirixtt/GeoJSON-Uzbekistan `uzbekistan_regional.geojson` (MIT)
- districts: geoBoundaries UZB ADM2 (CC BY 3.0 IGO, OCHA ROCCA), if data/reference/geo/ has it

Approach:
- regions are matched to SOATO by normalised English name;
- each district polygon is assigned to the region that contains most of it, then matched by normalised
  name (rapidfuzz >= MATCH_THRESHOLD) within that region and kind (city vs district);
- unmatched districts get an approximate centroid (manual CSV > parent city polygon > region point)
  with geom_approx = true and are listed in data/reference/unmatched_districts.csv.

Usage:  python pipelines/load_reference.py
"""

from __future__ import annotations

import csv
import io
import json
import re
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

import requests
from rapidfuzz import fuzz
from shapely import make_valid
from shapely.geometry import MultiPolygon, Polygon, mapping, shape
from shapely.geometry.base import BaseGeometry
from sqlalchemy import select, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.db.models import District, Region  # noqa: E402
from app.db.session import get_sessionmaker  # noqa: E402

GEO_DIR = ROOT / "data" / "reference" / "geo"
OUT_DIR = ROOT / "data" / "processed" / "geo"
REGIONS_ZIP = GEO_DIR / "dirixtt.zip"
REGIONS_URL = "https://codeload.github.com/dirixtt/GeoJSON-Uzbekistan/zip/refs/heads/main"
DISTRICTS_FILE = GEO_DIR / "geoBoundaries-UZB-ADM2.geojson"
# geoBoundaries stores files in Git LFS; media.githubusercontent.com serves the real content.
DISTRICTS_URL = (
    "https://media.githubusercontent.com/media/wmgeolab/geoBoundaries/9469f09/"
    "releaseData/gbOpen/UZB/ADM2/geoBoundaries-UZB-ADM2.geojson"
)
MANUAL_CENTROIDS = ROOT / "data" / "reference" / "district_centroids.csv"
UNMATCHED_FILE = ROOT / "data" / "reference" / "unmatched_districts.csv"
ALIASES_FILE = ROOT / "data" / "reference" / "geo_aliases.csv"  # source name -> SOATO for renamed units

SIMPLIFY_TOLERANCE = 0.005
MATCH_THRESHOLD = 90
OTHER_REGION_PENALTY = 10  # region polygons are coarse near Tashkent city; allow a neighbour, penalised

# Cyrillic letters that appear inside otherwise Latin source names (e.g. "Rаmitan").
CYR_LOOKALIKE = str.maketrans("аеорсхуАЕОРСХУ", "aeopcxyAEOPCXY")
SUFFIXES = r"\b(district|region|province|city|tumani|shahri|shahar|viloyati|sh)\b"
TRANSLIT = [
    ("dzh", "j"),
    ("dj", "j"),
    ("zh", "j"),
    ("kh", "x"),
    ("sh", "s"),
    ("ch", "c"),
    ("q", "k"),
    ("yo", "e"),
    ("ya", "a"),
    ("yu", "u"),
    ("ou", "u"),
    ("w", "v"),
    ("ts", "s"),
    ("h", "x"),
    ("e", "i"),
]


def normalise(name: str) -> str:
    """Transliteration-insensitive key: o'/oʻ/o‘, x/kh, q/k, 'tumani'/'district' are all equivalent."""
    s = name.translate(CYR_LOOKALIKE).lower()
    s = re.sub(r"[‘’ʻʼ'`´]", "", s)
    s = re.sub(SUFFIXES, " ", s)
    for a, b in TRANSLIT:
        s = s.replace(a, b)
    s = re.sub(r"[^a-z]+", "", s)
    s = re.sub(r"(.)\1+", r"\1", s)  # double letters
    return s.replace("o", "a").replace("i", "y")  # o/a and i/y vowel drift (Pap/Pop, Narin/Naryn)


def as_multipolygon(geom: BaseGeometry) -> MultiPolygon:
    """Valid MultiPolygon from any (possibly invalid or mixed) source geometry."""
    if not geom.is_valid:
        geom = make_valid(geom)
    if isinstance(geom, MultiPolygon):
        return geom
    if isinstance(geom, Polygon):
        return MultiPolygon([geom])
    polys = [g for g in getattr(geom, "geoms", []) if isinstance(g, Polygon | MultiPolygon)]
    parts: list[Polygon] = []
    for p in polys:
        parts.extend(p.geoms if isinstance(p, MultiPolygon) else [p])
    return MultiPolygon(parts)


def inner_point(geom: BaseGeometry) -> tuple[float, float]:
    """Centroid, or a guaranteed-interior point when the centroid falls outside (concave shapes)."""
    c = geom.centroid
    if not geom.contains(c):
        c = geom.representative_point()
    return c.y, c.x


# --- sources --------------------------------------------------------------------------------


def load_region_features() -> list[dict]:
    if not REGIONS_ZIP.exists():
        GEO_DIR.mkdir(parents=True, exist_ok=True)
        print(f"downloading {REGIONS_URL}")
        r = requests.get(REGIONS_URL, timeout=120)
        r.raise_for_status()
        REGIONS_ZIP.write_bytes(r.content)
    with zipfile.ZipFile(REGIONS_ZIP) as z:
        name = next(n for n in z.namelist() if n.endswith("uzbekistan_regional.geojson"))
        data = json.load(io.TextIOWrapper(z.open(name), encoding="utf-8"))
    return data["features"]


def load_district_features() -> list[dict]:
    if not DISTRICTS_FILE.exists():
        try:
            print(f"downloading {DISTRICTS_URL}")
            r = requests.get(DISTRICTS_URL, timeout=180)
            r.raise_for_status()
            GEO_DIR.mkdir(parents=True, exist_ok=True)
            DISTRICTS_FILE.write_bytes(r.content)
        except requests.RequestException as e:
            print(f"{DISTRICTS_FILE.name} unavailable ({type(e).__name__}) — districts use approximate centroids only.")
            return []
    return json.loads(DISTRICTS_FILE.read_text(encoding="utf-8"))["features"]


# --- matching -------------------------------------------------------------------------------


@dataclass
class GeoUnit:
    name: str
    kind: str  # city | district
    geom: MultiPolygon
    region_soato: str | None = None


def region_key(name: str) -> str:
    # "Tashkent city" and "Tashkent region" differ only by the suffix that normalise() drops.
    return normalise(name) + ("+city" if "city" in name.lower() else "")


def match_regions(features: list[dict], regions: list[Region]) -> dict[str, MultiPolygon]:
    by_key = {region_key(r.name_en): r.soato_code for r in regions}
    out: dict[str, MultiPolygon] = {}
    for f in features:
        en = f["properties"]["ADM1_EN"]
        key = region_key(en)
        best = max(by_key, key=lambda k: fuzz.ratio(k, key))
        if fuzz.ratio(best, key) < MATCH_THRESHOLD:
            raise ValueError(f"region '{en}' has no SOATO match")
        geom = as_multipolygon(shape(f["geometry"]).simplify(SIMPLIFY_TOLERANCE, preserve_topology=True))
        out[by_key[best]] = geom
    missing = {r.soato_code for r in regions} - set(out)
    if missing:
        raise ValueError(f"regions without geometry: {sorted(missing)}")
    return out


def assign_region(geom: BaseGeometry, regions: dict[str, MultiPolygon]) -> str | None:
    best, best_area = None, 0.0
    for soato, rg in regions.items():
        area = rg.intersection(geom).area if rg.intersects(geom) else 0.0
        if area > best_area:
            best, best_area = soato, area
    return best


def read_aliases() -> dict[str, str]:
    if not ALIASES_FILE.exists():
        return {}
    with ALIASES_FILE.open(encoding="utf-8") as f:
        return {
            normalise(r["source_name"]) + r["source_name"].lower().endswith(" city") * "+c": r["soato_code"]
            for r in csv.DictReader(f)
        }


def match_districts(
    units: list[GeoUnit], districts: list[District], region_soato_by_id: dict[int, str]
) -> tuple[dict[str, GeoUnit], list[tuple[District, str, float]]]:
    """Greedy best-pair matching on (kind, name), same region preferred. Returns matches + unmatched."""
    aliases = read_aliases()
    pairs: list[tuple[float, int, str]] = []
    for ui, u in enumerate(units):
        ukey = normalise(u.name)
        alias = aliases.get(ukey + (u.kind == "city") * "+c")
        for d in districts:
            if d.kind != u.kind:
                continue
            if alias is not None:
                score = 100.0 if d.soato_code == alias else 0.0
            else:
                score = max(fuzz.ratio(ukey, normalise(d.name_en)), fuzz.ratio(ukey, normalise(d.name_uz or "")))
                if region_soato_by_id[d.region_id] != u.region_soato:
                    score -= OTHER_REGION_PENALTY
            pairs.append((score, ui, d.soato_code))
    pairs.sort(reverse=True)
    used_units: set[int] = set()
    matched: dict[str, GeoUnit] = {}
    best_score: dict[str, float] = {}
    for score, ui, soato in pairs:
        best_score.setdefault(soato, score)
        if score < MATCH_THRESHOLD or ui in used_units or soato in matched:
            continue
        used_units.add(ui)
        matched[soato] = units[ui]
    unmatched = [(d, d.name_en, best_score.get(d.soato_code, 0.0)) for d in districts if d.soato_code not in matched]
    return matched, unmatched


def read_manual_centroids() -> dict[str, tuple[float, float] | str]:
    """soato -> (lat, lon), or -> parent SOATO whose polygon interior point is used."""
    if not MANUAL_CENTROIDS.exists():
        return {}
    out: dict[str, tuple[float, float] | str] = {}
    with MANUAL_CENTROIDS.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("lat") and r.get("lon"):
                out[r["soato_code"]] = (float(r["lat"]), float(r["lon"]))
            elif r.get("parent_soato"):
                out[r["soato_code"]] = r["parent_soato"]
    return out


# --- main -----------------------------------------------------------------------------------


def write_geojson(path: Path, features: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def round_coords(geom: dict, ndigits: int = 4) -> dict:
    def r(c):  # noqa: ANN001, ANN202
        return [r(x) for x in c] if isinstance(c[0], list | tuple) else [round(c[0], ndigits), round(c[1], ndigits)]

    return {"type": geom["type"], "coordinates": r(geom["coordinates"])}


def main() -> None:
    with get_sessionmaker()() as db:
        regions = db.scalars(select(Region)).all()
        districts = db.scalars(select(District)).all()
        if not regions:
            sys.exit("No regions in the database — run `python manage.py ingest --local` first.")
        region_soato_by_id = {r.id: r.soato_code for r in regions}

        region_geoms = match_regions(load_region_features(), regions)
        for r in regions:
            g = region_geoms[r.soato_code]
            r.centroid_lat, r.centroid_lon = inner_point(g)
            r.geom_approx = False
            db.execute(
                text("UPDATE regions SET geom = ST_Multi(ST_GeomFromGeoJSON(:g)) WHERE id = :id"),
                {"g": json.dumps(mapping(g)), "id": r.id},
            )

        units: list[GeoUnit] = []
        for f in load_district_features():
            name = f["properties"]["shapeName"].translate(CYR_LOOKALIKE)
            geom = as_multipolygon(shape(f["geometry"]).simplify(SIMPLIFY_TOLERANCE, preserve_topology=True))
            kind = "city" if name.lower().endswith(" city") else "district"
            units.append(GeoUnit(name=name, kind=kind, geom=geom, region_soato=assign_region(geom, region_geoms)))

        matched, unmatched = match_districts(units, districts, region_soato_by_id)
        manual = read_manual_centroids()
        by_soato = {d.soato_code: d for d in districts}
        for d in districts:
            u = matched.get(d.soato_code)
            if u is not None:
                d.centroid_lat, d.centroid_lon = inner_point(u.geom)
                d.geom_approx = False
                db.execute(
                    text("UPDATE districts SET geom = ST_Multi(ST_GeomFromGeoJSON(:g)) WHERE id = :id"),
                    {"g": json.dumps(mapping(u.geom)), "id": d.id},
                )
                continue
            d.geom_approx = True
            db.execute(text("UPDATE districts SET geom = NULL WHERE id = :id"), {"id": d.id})
            parent = matched.get(d.soato_code[:7]) if len(d.soato_code) > 7 else None
            m = manual.get(d.soato_code)
            if isinstance(m, tuple):
                d.centroid_lat, d.centroid_lon = m
            elif isinstance(m, str) and m in matched:  # inside the district it was formed from
                d.centroid_lat, d.centroid_lon = inner_point(matched[m].geom)
            elif parent is not None:  # sub-city district (10-digit SOATO) → parent city polygon
                d.centroid_lat, d.centroid_lon = inner_point(parent.geom)
            else:
                d.centroid_lat, d.centroid_lon = inner_point(region_geoms[region_soato_by_id[d.region_id]])
        db.commit()

        # exports for the frontend
        names = {r.soato_code: r for r in regions}
        write_geojson(
            OUT_DIR / "regions.geojson",
            [
                {
                    "type": "Feature",
                    "geometry": round_coords(mapping(region_geoms[s])),
                    "properties": {
                        "soato_code": s,
                        "name_en": names[s].name_en,
                        "name_uz": names[s].name_uz,
                        "name_ru": names[s].name_ru,
                    },
                }
                for s in sorted(region_geoms)
            ],
        )
        write_geojson(
            OUT_DIR / "districts.geojson",
            [
                {
                    "type": "Feature",
                    "geometry": round_coords(mapping(matched[s].geom))
                    if s in matched
                    else {"type": "Point", "coordinates": [by_soato[s].centroid_lon, by_soato[s].centroid_lat]},
                    "properties": {
                        "soato_code": s,
                        "region_soato": region_soato_by_id[by_soato[s].region_id],
                        "name_en": by_soato[s].name_en,
                        "name_uz": by_soato[s].name_uz,
                        "kind": by_soato[s].kind,
                        "geom_approx": s not in matched,
                    },
                }
                for s in sorted(by_soato)
            ],
        )

        with UNMATCHED_FILE.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["soato_code", "name_en", "name_uz", "kind", "region_soato", "best_score", "centroid_source"])
            for d, _, score in sorted(unmatched, key=lambda x: x[0].soato_code):
                src = (
                    "manual"
                    if d.soato_code in manual
                    else "parent_city"
                    if len(d.soato_code) > 7 and d.soato_code[:7] in matched
                    else "region"
                )
                w.writerow(
                    [
                        d.soato_code,
                        d.name_en,
                        d.name_uz,
                        d.kind,
                        region_soato_by_id[d.region_id],
                        round(score, 1),
                        src,
                    ]
                )

        unused = len(units) - len(matched)
        print(
            f"regions: {len(region_geoms)}/{len(regions)} with polygons\n"
            f"districts: {len(matched)} polygons, {len(unmatched)} approximate centroids "
            f"(listed in {UNMATCHED_FILE.relative_to(ROOT)}); {unused} source polygons unused"
        )


if __name__ == "__main__":
    main()
