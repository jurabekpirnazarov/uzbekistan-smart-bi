"""Official statistics: indicator catalogue, rankings, time series, dashboard KPIs.

All numbers are computed here (never by an LLM) and every response carries source metadata.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import Row, and_, func, select
from sqlalchemy.orm import Session

from app.db.models import DataSource, District, Indicator, Observation, Region

Level = Literal["country", "region", "district"]


class NotFoundError(LookupError):
    """Unknown indicator / territory — the API maps this to 404."""


# --- response models ---------------------------------------------------------------


class Source(BaseModel):
    name: str
    url: str | None
    siat_dataset_id: int | None = None


class Meta(BaseModel):
    indicator: str | None = None
    unit: str | None = None
    period: str | None = None
    sources: list[Source] = []
    is_synthetic: bool = False
    retrieved_at: datetime | None = None


class IndicatorOut(BaseModel):
    code: str
    name_en: str
    category: str
    unit: str
    additive: bool
    higher_is_better: bool
    levels: list[Level]
    year_min: int | None
    year_max: int | None
    source_name: str | None
    siat_dataset_id: int | None
    auto_added: bool = False  # newly published SIAT dataset mapped automatically (not reviewed, not scored)


class RegionOut(BaseModel):
    soato: str
    name_en: str
    name_uz: str | None
    name_ru: str | None
    districts: int


class DistrictOut(BaseModel):
    soato: str
    name_en: str
    name_uz: str | None
    name_ru: str | None
    kind: str
    region_soato: str


class RankingItem(BaseModel):
    rank: int
    soato: str
    name: str
    kind: str | None = None
    region_soato: str | None = None
    value: float
    share: float | None = None  # share of the parent total, only for additive indicators


class Ranking(BaseModel):
    level: Level
    year: int
    years_available: list[int]
    items: list[RankingItem]
    total: float | None  # sum over items, only for additive indicators
    meta: Meta


class Point(BaseModel):
    year: int
    value: float


class TimeSeries(BaseModel):
    level: Level
    soato: str
    name: str
    points: list[Point]
    meta: Meta


class Kpi(BaseModel):
    indicator: str
    label: str
    unit: str
    year: int
    value: float
    change_pct: float | None  # vs previous year


class Overview(BaseModel):
    kpis: list[Kpi]
    regions: int
    districts: int
    cities: int
    meta: Meta


# --- helpers ---------------------------------------------------------------------------


def _indicator(db: Session, code: str) -> Indicator:
    ind = db.scalar(select(Indicator).where(Indicator.code == code))
    if ind is None:
        raise NotFoundError(f"Unknown indicator '{code}'")
    return ind


def _annual(ind: Indicator, level: Level):  # noqa: ANN202
    return and_(
        Observation.indicator_id == ind.id,
        Observation.level == level,
        Observation.quarter.is_(None),
        Observation.month.is_(None),
    )


def _meta(db: Session, ind: Indicator, period: str | None) -> Meta:
    src = db.execute(
        select(
            DataSource.name,
            func.max(Observation.source_url),
            func.max(Observation.retrieved_at),
            func.bool_or(Observation.is_synthetic),
        )
        .join(Observation, Observation.source_id == DataSource.id)
        .where(Observation.indicator_id == ind.id)
        .group_by(DataSource.name)
    ).all()
    return Meta(
        indicator=ind.code,
        unit=ind.unit,
        period=period,
        sources=[Source(name=s[0], url=s[1], siat_dataset_id=ind.siat_dataset_id) for s in src],
        is_synthetic=any(bool(s[3]) for s in src),
        retrieved_at=max((s[2] for s in src if s[2]), default=None),
    )


# --- public service functions --------------------------------------------------------


def list_indicators(db: Session, category: str | None = None) -> list[IndicatorOut]:
    q = (
        select(
            Indicator,
            func.array_agg(func.distinct(Observation.level)),
            func.min(Observation.year),
            func.max(Observation.year),
        )
        .outerjoin(Observation, Observation.indicator_id == Indicator.id)
        .group_by(Indicator.id)
        .order_by(Indicator.category, Indicator.code)
    )
    if category:
        q = q.where(Indicator.category == category)
    order = {"country": 0, "region": 1, "district": 2}
    return [
        IndicatorOut(
            code=i.code,
            name_en=i.name_en,
            category=i.category,
            unit=i.unit,
            additive=i.additive,
            higher_is_better=i.higher_is_better,
            levels=sorted([lv for lv in levels if lv], key=order.__getitem__),
            year_min=y0,
            year_max=y1,
            source_name=i.source_name,
            siat_dataset_id=i.siat_dataset_id,
            auto_added=bool(i.auto_added),
        )
        for i, levels, y0, y1 in db.execute(q).all()
    ]


def list_regions(db: Session) -> list[RegionOut]:
    rows = db.execute(
        select(Region, func.count(District.id))
        .outerjoin(District, District.region_id == Region.id)
        .group_by(Region.id)
        .order_by(Region.name_en)
    ).all()
    return [
        RegionOut(soato=r.soato_code, name_en=r.name_en, name_uz=r.name_uz, name_ru=r.name_ru, districts=n)
        for r, n in rows
    ]


def list_districts(db: Session, region_soato: str) -> list[DistrictOut]:
    region = db.scalar(select(Region).where(Region.soato_code == region_soato))
    if region is None:
        raise NotFoundError(f"Unknown region '{region_soato}'")
    rows = db.scalars(select(District).where(District.region_id == region.id).order_by(District.name_en)).all()
    return [
        DistrictOut(
            soato=d.soato_code,
            name_en=d.name_en,
            name_uz=d.name_uz,
            name_ru=d.name_ru,
            kind=d.kind,
            region_soato=region_soato,
        )
        for d in rows
    ]


def get_ranking(
    db: Session,
    indicator: str,
    level: Literal["region", "district"] = "region",
    year: int | None = None,
    region: str | None = None,
) -> Ranking:
    ind = _indicator(db, indicator)
    base = _annual(ind, level)
    region_id = None
    if region:
        region_id = db.scalar(select(Region.id).where(Region.soato_code == region))
        if region_id is None:
            raise NotFoundError(f"Unknown region '{region}'")
        base = and_(base, Observation.region_id == region_id)

    years = sorted({y for (y,) in db.execute(select(Observation.year).where(base).distinct())}, reverse=True)
    if not years:
        raise NotFoundError(f"No {level}-level data for '{indicator}'")
    if year is None:
        year = years[0]
    elif year not in years:
        raise NotFoundError(f"No data for '{indicator}' in {year}; available: {years}")

    if level == "region":
        rows: list[Row] = db.execute(
            select(Region.soato_code, Region.name_en, Observation.value)
            .join(Region, Region.id == Observation.region_id)
            .where(base, Observation.year == year)
        ).all()
        items = [(s, n, None, None, v) for s, n, v in rows]
    else:
        rows = db.execute(
            select(District.soato_code, District.name_en, District.kind, Region.soato_code, Observation.value)
            .join(District, District.id == Observation.district_id)
            .join(Region, Region.id == District.region_id)
            .where(base, Observation.year == year)
        ).all()
        items = [tuple(r) for r in rows]

    items.sort(key=lambda r: r[4], reverse=ind.higher_is_better)
    total = sum(r[4] for r in items) if ind.additive else None
    return Ranking(
        level=level,
        year=year,
        years_available=years,
        items=[
            RankingItem(rank=i, soato=s, name=n, kind=k, region_soato=rs, value=v, share=(v / total) if total else None)
            for i, (s, n, k, rs, v) in enumerate(items, 1)
        ],
        total=total,
        meta=_meta(db, ind, str(year)),
    )


def get_timeseries(db: Session, indicator: str, level: Level, soato: str) -> TimeSeries:
    ind = _indicator(db, indicator)
    if level == "country":
        name, cond = "Republic of Uzbekistan", True
    elif level == "region":
        r = db.scalar(select(Region).where(Region.soato_code == soato))
        if r is None:
            raise NotFoundError(f"Unknown region '{soato}'")
        name, cond = r.name_en, Observation.region_id == r.id
    else:
        d = db.scalar(select(District).where(District.soato_code == soato))
        if d is None:
            raise NotFoundError(f"Unknown district '{soato}'")
        name, cond = d.name_en, Observation.district_id == d.id
    rows = db.execute(
        select(Observation.year, Observation.value).where(_annual(ind, level), cond).order_by(Observation.year)
    ).all()
    points = [Point(year=y, value=v) for y, v in rows]
    period = f"{points[0].year}–{points[-1].year}" if points else None
    return TimeSeries(level=level, soato=soato, name=name, points=points, meta=_meta(db, ind, period))


KPI_SPECS = [
    ("population_total", "Population"),
    ("enterprises_active", "Operating businesses"),
    ("enterprises_new", "New businesses"),
    ("market_services_volume", "Market services"),
]


def get_overview(db: Session) -> Overview:
    kpis = []
    for code, label in KPI_SPECS:
        ind = db.scalar(select(Indicator).where(Indicator.code == code))
        if ind is None:
            continue
        rows = db.execute(
            select(Observation.year, Observation.value)
            .where(_annual(ind, "country"))
            .order_by(Observation.year.desc())
            .limit(2)
        ).all()
        if not rows:
            continue
        (y, v), prev = rows[0], (rows[1][1] if len(rows) > 1 else None)
        kpis.append(
            Kpi(
                indicator=code,
                label=label,
                unit=ind.unit,
                year=y,
                value=v,
                change_pct=((v - prev) / prev * 100) if prev else None,
            )
        )
    counts = dict(db.execute(select(District.kind, func.count()).group_by(District.kind)).all())
    src = db.execute(select(DataSource.name, DataSource.url, DataSource.retrieved_at)).all()
    return Overview(
        kpis=kpis,
        regions=db.scalar(select(func.count(Region.id))) or 0,
        districts=counts.get("district", 0),
        cities=counts.get("city", 0),
        meta=Meta(
            sources=[Source(name=n, url=u) for n, u, _ in src],
            retrieved_at=max((r for *_, r in src if r), default=None),
        ),
    )


# --- territory lookup and comparison ------------------------------------------------------------

_NAME_NOISE = re.compile(
    r"\b(region|province|district|city|republic of|viloyati|viloyat|tumani|tuman|shahri|shahar|"
    r"область|обл|район|город|г|respublikasi|республика)\b"
)


def _name_key(s: str) -> str:
    s = s.lower().translate(str.maketrans("‘’ʻʼ`´", "''''''")).replace("'", "")
    s = _NAME_NOISE.sub(" ", s)
    return re.sub(r"[^\w]+", "", s)


class TerritoryMatch(BaseModel):
    level: Level
    soato: str
    name: str
    region_soato: str | None
    score: float


def find_territory(db: Session, query: str, level: Level | None = None, limit: int = 5) -> list[TerritoryMatch]:
    """Fuzzy match a territory by SOATO or name in English, Uzbek or Russian (best first)."""
    from rapidfuzz import fuzz

    q = query.strip()
    if q in ("1700", "uzbekistan", "Uzbekistan", "O‘zbekiston", "Узбекистан"):
        return [
            TerritoryMatch(level="country", soato="1700", name="Republic of Uzbekistan", region_soato=None, score=100)
        ]
    cands: list[tuple[Level, str, str, str | None, list[str | None]]] = []
    if level in (None, "region"):
        for r in db.scalars(select(Region)).all():
            cands.append(("region", r.soato_code, r.name_en, r.soato_code, [r.name_en, r.name_uz, r.name_ru]))
    if level in (None, "district"):
        rows = db.execute(select(District, Region.soato_code).join(Region, Region.id == District.region_id)).all()
        for d, rs in rows:
            cands.append(("district", d.soato_code, d.name_en, rs, [d.name_en, d.name_uz, d.name_ru]))
    exact = [c for c in cands if c[1] == q]
    if exact:
        c = exact[0]
        return [TerritoryMatch(level=c[0], soato=c[1], name=c[2], region_soato=c[3], score=100)]
    key = _name_key(q)
    if not key:
        return []
    scored = []
    for lv, soato, name, rs, names in cands:
        s = max(fuzz.ratio(key, _name_key(n)) for n in names if n)
        # "Fergana" alone means the region more often than the district of the same name
        s += 2 if lv == "region" else 0
        # "Fergana city" should prefer the city over the region/district
        if any(w in q.lower() for w in ("city", "shahri", "shahar", "город")) and "city" in name.lower():
            s += 5
        scored.append((s, lv, soato, name, rs))
    scored.sort(key=lambda x: -x[0])
    return [
        TerritoryMatch(level=lv, soato=soato, name=name, region_soato=rs, score=round(min(s, 100), 1))
        for s, lv, soato, name, rs in scored[:limit]
        if s >= 70
    ]


def level_of(soato: str) -> Level:
    return "country" if soato == "1700" else "region" if len(soato) == 4 else "district"


class ComparisonRow(BaseModel):
    soato: str
    name: str
    level: Level
    value: float | None
    rank: str | None
    per_1000_people: float | None


class Comparison(BaseModel):
    indicator: str
    year: int
    rows: list[ComparisonRow]
    meta: Meta


def compare(db: Session, indicator: str, entities: list[str], year: int | None = None) -> Comparison:
    """Side-by-side values of one indicator; per-1,000-people values for additive non-population indicators."""
    ind = _indicator(db, indicator)
    if not entities:
        raise NotFoundError("No entities given")
    rows: list[ComparisonRow] = []
    used_year: int | None = year
    for lv in ("region", "district"):
        wanted = [e for e in entities if level_of(e) == lv]
        if not wanted:
            continue
        r = get_ranking(db, indicator, lv, year)  # type: ignore[arg-type]
        used_year = r.year
        pop = {}
        if ind.additive and ind.unit != "persons":
            try:
                pop = {i.soato: i.value for i in get_ranking(db, "population_total", lv, r.year).items}  # type: ignore[arg-type]
            except NotFoundError:
                pop = {}
        by = {i.soato: i for i in r.items}
        for e in wanted:
            it = by.get(e)
            rows.append(
                ComparisonRow(
                    soato=e,
                    name=it.name if it else e,
                    level=lv,
                    value=it.value if it else None,
                    rank=f"{it.rank}/{len(r.items)}" if it else None,
                    per_1000_people=round(it.value / pop[e] * 1000, 4) if it and pop.get(e) else None,
                )
            )
    if used_year is None:
        raise NotFoundError("Only region / district SOATO codes can be compared")
    return Comparison(indicator=indicator, year=used_year, rows=rows, meta=_meta(db, ind, str(used_year)))
