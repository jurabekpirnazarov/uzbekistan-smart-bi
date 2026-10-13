"""MCP server (FastMCP, PLAN.md Phase 7). Tools are thin wrappers over app.services — no business logic here.

Every tool returns {"data": ..., "meta": {"sources": [...], "is_synthetic": bool, "period": str | None},
"warnings": [...]}; failures return {"error": {"code", "message"}} instead of raising.

Run:
    python -m mcp_server.server                     # streamable-http on :8100 (path /mcp)
    python -m mcp_server.server --transport stdio   # for Claude Desktop / MCP Inspector over stdio
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "backend"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from mcp.server.fastmcp import FastMCP  # noqa: E402
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest  # noqa: E402
from starlette.requests import Request  # noqa: E402
from starlette.responses import JSONResponse, Response  # noqa: E402

from app import __version__  # noqa: E402
from app.core import metrics  # noqa: E402
from app.db.session import get_sessionmaker  # noqa: E402
from app.services import chat as agent_tools  # noqa: E402
from app.services import documents, forecasts, recommendations  # noqa: E402
from app.services import statistics as stats  # noqa: E402
from app.services.health import get_health  # noqa: E402

mcp = FastMCP(
    "uz-smart-bi",
    host=os.getenv("MCP_HOST", "0.0.0.0"),
    port=int(os.getenv("MCP_PORT", "8100")),
)

NO_DISTRICT_INCOME = (
    "There is no official district-level income or wage data in this system. "
    "I don't have sufficient official data to answer this reliably."
)


def _meta(meta: Any) -> dict:
    if isinstance(meta, stats.Meta):
        return {
            "sources": [s.model_dump() for s in meta.sources],
            "is_synthetic": meta.is_synthetic,
            "period": meta.period,
        }
    return {"sources": [], "is_synthetic": False, "period": None}


def _run(tool: str, fn: Callable[[Any], dict]) -> dict:
    """Open a session, run the tool, record metrics, turn errors into structured results."""
    t0 = time.perf_counter()
    status = "ok"
    try:
        with get_sessionmaker()() as db:
            return fn(db)
    except stats.NotFoundError as e:
        status = "not_found"
        return {"error": {"code": "not_found", "message": str(e)}}
    except (ValueError, TypeError) as e:
        status = "bad_arguments"
        return {"error": {"code": "bad_arguments", "message": str(e)}}
    except Exception as e:  # never crash the MCP session
        status = "error"
        return {"error": {"code": "internal", "message": type(e).__name__}}
    finally:
        metrics.MCP_TOOL_CALLS.labels(tool, status).inc()
        metrics.MCP_TOOL_LATENCY.labels(tool).observe(time.perf_counter() - t0)


def _resolve(db: Any, entity: str | None, level: str | None = None) -> stats.TerritoryMatch:
    if not entity:
        return stats.TerritoryMatch(
            level="country", soato="1700", name="Republic of Uzbekistan", region_soato=None, score=100
        )
    found = stats.find_territory(db, entity, level)  # type: ignore[arg-type]
    if not found:
        raise stats.NotFoundError(f"No territory matches '{entity}'")
    return found[0]


def _values(db: Any, indicators: list[str], level: str, entity: str | None, year: int | None) -> dict:
    """Value of each indicator for one territory (or every territory of a level when entity is None)."""
    data, metas, warnings = {}, [], []
    for code in indicators:
        if entity is None and level in ("region", "district"):
            r = stats.get_ranking(db, code, level, year)  # type: ignore[arg-type]
            data[code] = {"year": r.year, "items": [i.model_dump() for i in r.items]}
            metas.append(r.meta)
            continue
        t = _resolve(db, entity, None if level == "country" else level)
        ts = stats.get_timeseries(db, code, t.level, t.soato)
        pts = {p.year: p.value for p in ts.points}
        if not pts:
            warnings.append(f"No {t.level}-level data for {code}")
            continue
        y = year if year in pts else max(pts)
        if year and year not in pts:
            warnings.append(f"{code}: {year} not available, using {y}")
        data[code] = {"territory": t.name, "soato": t.soato, "level": t.level, "year": y, "value": pts[y]}
        metas.append(ts.meta)
    sources = {s["url"]: s for m in metas for s in _meta(m)["sources"]}
    return {
        "data": data,
        "meta": {"sources": list(sources.values()), "is_synthetic": any(m.is_synthetic for m in metas), "period": None},
        "warnings": warnings,
    }


# --- tools ---------------------------------------------------------------------------------------


@mcp.tool()
def ping() -> dict:
    """Check that the MCP server and its database are reachable."""
    health = get_health(__version__)
    return {"data": {"pong": True, "db": health.db}, "meta": {"version": __version__}, "warnings": []}


@mcp.tool()
def search_statistics(query: str, category: str | None = None) -> dict:
    """Find indicators by keyword (English name, code or category) in the official catalogue."""

    def fn(db: Any) -> dict:
        q = query.lower()
        hits = [
            i.model_dump()
            for i in stats.list_indicators(db, category)
            if q in i.code.lower() or q in i.name_en.lower() or q in (i.source_name or "").lower() or q in i.category
        ]
        return {"data": hits, "meta": _meta(None), "warnings": [] if hits else [f"No indicator matches '{query}'"]}

    return _run("search_statistics", fn)


@mcp.tool()
def get_indicator(code: str) -> dict:
    """Metadata of one internal indicator: unit, levels, years, SIAT dataset id."""

    def fn(db: Any) -> dict:
        for i in stats.list_indicators(db):
            if i.code == code:
                return {"data": i.model_dump(), "meta": _meta(None), "warnings": []}
        raise stats.NotFoundError(f"Unknown indicator '{code}'")

    return _run("get_indicator", fn)


@mcp.tool()
def get_region_statistics(region: str, indicators: list[str], year: int | None = None) -> dict:
    """Values of several indicators for one region (name in en/uz/ru or SOATO code)."""
    return _run("get_region_statistics", lambda db: _values(db, indicators, "region", region, year))


@mcp.tool()
def get_district_statistics(
    region: str, indicators: list[str], district: str | None = None, year: int | None = None
) -> dict:
    """Values for one district, or for every district of a region when `district` is omitted."""

    def fn(db: Any) -> dict:
        if district:
            return _values(db, indicators, "district", district, year)
        reg = _resolve(db, region, "region")
        data, metas = {}, []
        for code in indicators:
            r = stats.get_ranking(db, code, "district", year, reg.soato)
            data[code] = {"year": r.year, "items": [i.model_dump() for i in r.items]}
            metas.append(r.meta)
        sources = {s["url"]: s for m in metas for s in _meta(m)["sources"]}
        return {
            "data": data,
            "meta": {"sources": list(sources.values()), "is_synthetic": False, "period": None},
            "warnings": [],
        }

    return _run("get_district_statistics", fn)


@mcp.tool()
def get_time_series(
    indicator: str, level: str, entity: str, year_from: int | None = None, year_to: int | None = None
) -> dict:
    """Yearly history of an indicator for the country ("1700"), a region or a district."""

    def fn(db: Any) -> dict:
        t = _resolve(db, entity, None if level == "country" else level)
        ts = stats.get_timeseries(db, indicator, t.level, t.soato)
        pts = [p.model_dump() for p in ts.points if (year_from or 0) <= p.year <= (year_to or 9999)]
        return {"data": {"territory": ts.name, "soato": t.soato, "points": pts}, "meta": _meta(ts.meta), "warnings": []}

    return _run("get_time_series", fn)


@mcp.tool()
def compare_regions(entities: list[str], indicators: list[str], year: int | None = None) -> dict:
    """Side-by-side values (and per-1,000-people values) for several regions or districts."""

    def fn(db: Any) -> dict:
        soatos = [_resolve(db, e).soato for e in entities]
        out = {code: stats.compare(db, code, soatos, year).model_dump(mode="json") for code in indicators}
        metas = [o["meta"] for o in out.values()]
        return {
            "data": {k: {"year": v["year"], "rows": v["rows"]} for k, v in out.items()},
            "meta": {"sources": [s for m in metas for s in m["sources"]], "is_synthetic": False, "period": None},
            "warnings": [],
        }

    return _run("compare_regions", fn)


@mcp.tool()
def get_population_data(level: str = "country", entity: str | None = None, year: int | None = None) -> dict:
    """Total, urban and rural permanent population."""
    inds = ["population_total", "population_urban", "population_rural"]
    return _run("get_population_data", lambda db: _values(db, inds, level, entity, year))


@mcp.tool()
def get_income_data(level: str = "region", entity: str | None = None, year: int | None = None) -> dict:
    """Household income / wages. Not available in the official warehouse — returns a clear warning."""
    return {"data": None, "meta": _meta(None), "warnings": [NO_DISTRICT_INCOME]}


@mcp.tool()
def get_business_activity(level: str = "country", entity: str | None = None, year: int | None = None) -> dict:
    """Operating, registered and newly created business entities."""
    inds = ["enterprises_active", "enterprises_registered", "enterprises_new"]
    return _run("get_business_activity", lambda db: _values(db, inds, level, entity, year))


@mcp.tool()
def get_retail_data(level: str = "country", entity: str | None = None, year: int | None = None) -> dict:
    """Trade services volume and growth (the closest official proxy for retail turnover by district)."""

    def fn(db: Any) -> dict:
        out = _values(db, ["trade_services_volume", "trade_services_growth"], level, entity, year)
        out["warnings"].append("Retail trade turnover by district is not published; trade services are a proxy.")
        return out

    return _run("get_retail_data", fn)


@mcp.tool()
def forecast_indicator(indicator: str, level: str, entity: str, horizon: int = 3) -> dict:
    """Model forecast (1–3 years) with 80/95 % intervals — a model prediction, not an official statistic."""

    def fn(db: Any) -> dict:
        t = _resolve(db, entity, None if level == "country" else level)
        f = forecasts.get_forecast(db, indicator, t.level, t.soato, max(1, min(horizon, 3)))
        warnings = [f.note] + (["Short history: low confidence."] if f.low_confidence else [])
        return {"data": f.model_dump(mode="json", exclude={"meta"}), "meta": _meta(f.meta), "warnings": warnings}

    return _run("forecast_indicator", fn)


@mcp.tool()
def calculate_business_score(
    business_type: str,
    region: str | None = None,
    target: str | None = None,
    weights_override: dict[str, float] | None = None,
    budget_uzs: int | None = None,
    limit: int = 10,
) -> dict:
    """Business Opportunity Score with factor breakdown (an analytical model — decision support only)."""

    def fn(db: Any) -> dict:
        reg = _resolve(db, region, "region").soato if region else None
        res = recommendations.recommend(
            db,
            recommendations.RecommendRequest(
                business_type=business_type,
                region=reg,
                target=target,  # type: ignore[arg-type]
                weights_override=weights_override,
                budget_uzs=budget_uzs,
                limit=limit,
            ),
        )
        sources = {s["url"]: s for r in res["results"] for b in r["breakdown"] for s in b["sources"]}
        return {
            "data": res,
            "meta": {"sources": list(sources.values()), "is_synthetic": res["data_mode"] == "demo", "period": None},
            "warnings": [res["disclaimer"]],
        }

    return _run("calculate_business_score", fn)


@mcp.tool()
def list_business_types() -> dict:
    """Business profiles available for scoring (YAML profiles)."""
    return {
        "data": [b.model_dump() for b in recommendations.list_business_types()],
        "meta": _meta(None),
        "warnings": [],
    }


@mcp.tool()
def retrieve_documents(query: str, k: int = 5) -> dict:
    """Search SIAT methodology and project documentation (hybrid BM25 + embeddings when available)."""

    def fn(db: Any) -> dict:
        res = documents.retrieve_documents(db, query, k)
        return {"data": res["results"], "meta": _meta(None), "warnings": res["warnings"]}

    return _run("retrieve_documents", fn)


# The agent's growth tool is useful for MCP clients too (same implementation, no duplication).
@mcp.tool()
def get_growth_ranking(
    indicator: str, level: str, year_from: int, year_to: int | None = None, region: str | None = None, limit: int = 20
) -> dict:
    """Rank all regions or districts by growth of an indicator between two years (% change and CAGR)."""

    def fn(db: Any) -> dict:
        reg = _resolve(db, region, "region").soato if region else None
        res = agent_tools.tool_get_growth_ranking(db, indicator, level, year_from, year_to, reg, limit)
        return {"data": {k: v for k, v in res.items() if k != "meta"}, "meta": res["meta"], "warnings": []}

    return _run("get_growth_ranking", fn)


# --- ops routes --------------------------------------------------------------------------------------


@mcp.custom_route("/health", methods=["GET"])
async def health_route(_: Request) -> Response:
    return JSONResponse({"status": "ok", "version": __version__})


@mcp.custom_route("/metrics", methods=["GET"])
async def metrics_route(_: Request) -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


def main() -> None:
    parser = argparse.ArgumentParser(description="Uzbekistan Smart BI MCP server")
    parser.add_argument("--transport", choices=["streamable-http", "stdio"], default="streamable-http")
    args = parser.parse_args()
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
