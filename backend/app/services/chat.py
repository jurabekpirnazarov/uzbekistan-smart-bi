"""AI analyst chat: OpenAI tool-calling over the official-statistics services.

Rules enforced here (CLAUDE.md):
- The LLM never computes numbers: every figure (values, shares, growth, CAGR, comparisons) comes from a tool.
- No invented statistics: when tools return nothing, the model must say data is insufficient.
- Answers separate "Official statistics" / "Model prediction" / "AI interpretation" and cite SIAT sources.
- Every number in the final answer is checked against tool results (app.services.verify).
- Without OPENAI_API_KEY the rule-based planner in app.services.agent_fallback answers instead.
- Every run is logged to agent_runs / agent_tool_calls and to Prometheus metrics.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable, Iterator
from typing import Any

from openai import OpenAI
from sqlalchemy.orm import Session

from app.core import metrics
from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.models import AgentRun, AgentToolCall
from app.db.session import get_sessionmaker
from app.services import agent_fallback, documents, forecasts, recommendations
from app.services import statistics as stats
from app.services.verify import verify_answer

log = get_logger("chat")

MAX_TOOL_ROUNDS = 8
INSUFFICIENT = "I don't have sufficient official data to answer this reliably."

SYSTEM_PROMPT = """You are the AI analyst of "Uzbekistan Smart Business Intelligence".
You help entrepreneurs and analysts understand official statistics of Uzbekistan (source: SIAT, siat.stat.uz)
and reason about where business opportunities are.

STRICT RULES
1. Never invent or compute numbers yourself. Every number you write must come from a tool result
   (values, ranks, shares, growth rates, CAGR, differences). If you need a change or comparison, call
   `compute_change` or `compare_territories`. Rounding a tool number for readability is fine.
   Never subtract, add or divide values of different territories yourself (no "X more people than Y",
   no "N times larger"): show both official values side by side and let the reader compare. An answer
   checker flags every number that does not appear in a tool result.
2. If the tools return no data for the question, say exactly: "{insufficient}" (translated into the user's
   language) and explain what data is missing. Never fill gaps with general knowledge numbers.
3. Reply in the user's language (Uzbek, Russian or English) — match the language of the last user message.
   For Uzbek use Latin script.
4. Structure every analytical answer with these sections (translated headings), keeping the layers separate:
   **Official statistics** — ONLY observed values from statistics tools (rankings, time series, comparisons),
     with year and unit. Never put scores or forecasts here.
   **Model prediction** — only when you used `calculate_business_score` or `forecast_indicator`: scores,
     rank ranges, factor contributions, forecasts with their 80% interval and model name. Say these are model
     outputs, not statistics. The raw factor values inside a score breakdown (population, spending, …) are
     official statistics and may be quoted in the first section with their year.
   **AI interpretation** — your reasoning, clearly labelled as interpretation, not fact.
   **Sources** — SIAT dataset ids/links from the tool `meta` / `sources`.
   Short factual questions may use a compact form, but always name the year and source.
5. Units: values are already converted — persons (not thousands), UZS (not billions). Present large numbers
   readably (e.g. "4.38 million people", "397.4 trillion UZS"). Growth indicators named "...growth"
   are "% of previous year" (112.3 means +12.3%).
6. There is NO official district-level income or wage data in this system. Say so if asked.
7. Use markdown: short paragraphs, bullet lists, and small tables for rankings.
8. Method: for "fastest growing / grew most / o'sish / рост" questions ALWAYS call `get_growth_ranking`
   (it ranks every territory by growth in one call) — never pick territories by size first.
   Use the latest available year unless the user names one.
9. For "where should I open X / best place for X" questions call `calculate_business_score` (business types:
   {business_types}). Show the top results with score, rank range and the 2–3 largest factor contributions,
   and always include this disclaimer in the user's language: "{disclaimer}". If the user mentions a budget,
   pass it as budget_uzs and report the budget warning if there is one.
10. For future values call `forecast_indicator`; for methodology / definitions call `retrieve_documents` and cite
   the document titles. To resolve a place name to a SOATO code call `find_territory`.
11. If a result has is_synthetic=true, label it "DEMO / SYNTHETIC DATA — not official statistics".

DATA CATALOGUE (internal indicator codes — use these in tool calls)
{indicators}

REGIONS (SOATO codes)
{regions}

To work at district level, call `list_districts` for the region first to get district SOATO codes.
The national total uses level "country" with soato "1700".
"""

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_ranking",
            "description": "Rank regions or districts by an indicator for one year (latest if omitted). "
            "Returns values, ranks and (for additive indicators) shares of the total.",
            "parameters": {
                "type": "object",
                "properties": {
                    "indicator": {"type": "string", "description": "internal indicator code"},
                    "level": {"type": "string", "enum": ["region", "district"]},
                    "year": {"type": "integer"},
                    "region": {"type": "string", "description": "region SOATO, to rank only its districts"},
                    "limit": {"type": "integer", "description": "max items to return (default 20)"},
                    "order": {"type": "string", "enum": ["top", "bottom"], "description": "default top"},
                },
                "required": ["indicator", "level"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_timeseries",
            "description": "Yearly history of an indicator for the country, one region or one district.",
            "parameters": {
                "type": "object",
                "properties": {
                    "indicator": {"type": "string"},
                    "level": {"type": "string", "enum": ["country", "region", "district"]},
                    "soato": {"type": "string", "description": "1700 for the country"},
                },
                "required": ["indicator", "level", "soato"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_growth_ranking",
            "description": "Rank ALL regions or districts by growth of an indicator between two years in one call "
            "(% change and CAGR). Prefer this over many compute_change calls.",
            "parameters": {
                "type": "object",
                "properties": {
                    "indicator": {"type": "string"},
                    "level": {"type": "string", "enum": ["region", "district"]},
                    "year_from": {"type": "integer"},
                    "year_to": {"type": "integer", "description": "latest year if omitted"},
                    "region": {"type": "string", "description": "region SOATO, to rank only its districts"},
                    "limit": {"type": "integer", "description": "max items (default 20)"},
                    "order": {"type": "string", "enum": ["top", "bottom"]},
                },
                "required": ["indicator", "level", "year_from"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compute_change",
            "description": "Absolute change, % change and CAGR of an indicator between two years for one territory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "indicator": {"type": "string"},
                    "level": {"type": "string", "enum": ["country", "region", "district"]},
                    "soato": {"type": "string"},
                    "year_from": {"type": "integer"},
                    "year_to": {"type": "integer", "description": "latest year if omitted"},
                },
                "required": ["indicator", "level", "soato", "year_from"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_territories",
            "description": "Side-by-side values of several indicators for several territories in one year, "
            "plus per-capita values (per 1,000 people) for additive indicators when population is available.",
            "parameters": {
                "type": "object",
                "properties": {
                    "level": {"type": "string", "enum": ["region", "district"]},
                    "soatos": {"type": "array", "items": {"type": "string"}, "maxItems": 15},
                    "indicators": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
                    "year": {"type": "integer", "description": "latest common year if omitted"},
                },
                "required": ["level", "soatos", "indicators"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_districts",
            "description": "Districts and cities of a region with their SOATO codes.",
            "parameters": {
                "type": "object",
                "properties": {"region": {"type": "string", "description": "region SOATO"}},
                "required": ["region"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_overview",
            "description": "National headline KPIs (population, businesses, services) with year-on-year change.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_territory",
            "description": "Resolve a place name (English, Uzbek or Russian) to region/district SOATO codes.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_business_score",
            "description": "Business Opportunity Score (analytical model): ranks districts (of a region, or "
            "nationwide) for a business type, with factor breakdown, rank range and coverage.",
            "parameters": {
                "type": "object",
                "properties": {
                    "business_type": {"type": "string"},
                    "region": {"type": "string", "description": "region SOATO; omit for all districts nationwide"},
                    "level": {"type": "string", "enum": ["region", "district"], "description": "default district"},
                    "target": {"type": "string", "enum": ["high_growth", "stable_demand", "low_competition"]},
                    "budget_uzs": {"type": "integer"},
                    "limit": {"type": "integer", "description": "results to return (default 5)"},
                },
                "required": ["business_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "forecast_indicator",
            "description": "Model forecast (1–3 years) with 80%/95% intervals and backtest error, for "
            "population_total, enterprises_active, enterprises_new and services volumes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "indicator": {"type": "string"},
                    "level": {"type": "string", "enum": ["country", "region", "district"]},
                    "soato": {"type": "string"},
                    "horizon": {"type": "integer", "description": "1–3, default 3"},
                },
                "required": ["indicator", "level", "soato"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "retrieve_documents",
            "description": "Search SIAT methodology, indicator definitions and project documentation "
            "(scoring method, features, limitations). Returns cited snippets.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}, "k": {"type": "integer"}},
                "required": ["query"],
            },
        },
    },
]

TOOL_LABELS = {
    "get_ranking": "Ranking territories",
    "get_timeseries": "Loading history",
    "compute_change": "Computing growth",
    "get_growth_ranking": "Ranking by growth",
    "compare_territories": "Comparing territories",
    "list_districts": "Listing districts",
    "get_overview": "Loading national KPIs",
    "find_territory": "Finding the territory",
    "calculate_business_score": "Scoring locations",
    "forecast_indicator": "Forecasting",
    "retrieve_documents": "Searching methodology",
}


# --- tool implementations (pure Python; the LLM only sees their results) ---------------------


def _meta(meta: stats.Meta) -> dict:
    return {
        "unit": meta.unit,
        "period": meta.period,
        "is_synthetic": meta.is_synthetic,
        "sources": [{"siat_dataset_id": s.siat_dataset_id, "url": s.url} for s in meta.sources],
    }


def tool_get_ranking(
    db: Session,
    indicator: str,
    level: str,
    year: int | None = None,
    region: str | None = None,
    limit: int = 20,
    order: str = "top",
) -> dict:
    r = stats.get_ranking(db, indicator, level, year, region)  # type: ignore[arg-type]
    items = r.items if order == "top" else list(reversed(r.items))
    limit = max(1, min(limit or 20, 60))
    return {
        "indicator": indicator,
        "level": level,
        "year": r.year,
        "years_available": r.years_available,
        "territories_total": len(r.items),
        "order": order,
        "total": r.total,
        "items": [
            {
                "rank": i.rank,
                "name": i.name,
                "soato": i.soato,
                "kind": i.kind,
                "value": i.value,
                "share_of_total_pct": round(i.share * 100, 2) if i.share is not None else None,
            }
            for i in items[:limit]
        ],
        "meta": _meta(r.meta),
    }


def tool_get_timeseries(db: Session, indicator: str, level: str, soato: str) -> dict:
    t = stats.get_timeseries(db, indicator, level, soato)  # type: ignore[arg-type]
    return {
        "indicator": indicator,
        "territory": t.name,
        "level": level,
        "soato": soato,
        "points": [p.model_dump() for p in t.points],
        "meta": _meta(t.meta),
    }


def tool_compute_change(
    db: Session, indicator: str, level: str, soato: str, year_from: int, year_to: int | None = None
) -> dict:
    t = stats.get_timeseries(db, indicator, level, soato)  # type: ignore[arg-type]
    pts = {p.year: p.value for p in t.points}
    if not pts:
        return {"error": "no data", "message": INSUFFICIENT}
    year_to = year_to or max(pts)
    if year_from not in pts or year_to not in pts:
        return {"error": "year not available", "years_available": sorted(pts)}
    a, b = pts[year_from], pts[year_to]
    n = year_to - year_from
    return {
        "indicator": indicator,
        "territory": t.name,
        "year_from": year_from,
        "value_from": a,
        "year_to": year_to,
        "value_to": b,
        "absolute_change": b - a,
        "pct_change": round((b - a) / a * 100, 2) if a else None,
        "cagr_pct": round(((b / a) ** (1 / n) - 1) * 100, 2) if a and a > 0 and b > 0 and n > 0 else None,
        "meta": _meta(t.meta),
    }


def tool_get_growth_ranking(
    db: Session,
    indicator: str,
    level: str,
    year_from: int,
    year_to: int | None = None,
    region: str | None = None,
    limit: int = 20,
    order: str = "top",
) -> dict:
    end = stats.get_ranking(db, indicator, level, year_to, region)  # type: ignore[arg-type]
    start = stats.get_ranking(db, indicator, level, year_from, region)  # type: ignore[arg-type]
    base = {i.soato: i.value for i in start.items}
    n = end.year - year_from
    rows = []
    for i in end.items:
        a = base.get(i.soato)
        if a is None:
            continue
        rows.append(
            {
                "name": i.name,
                "soato": i.soato,
                "kind": i.kind,
                "value_from": a,
                "value_to": i.value,
                "pct_change": round((i.value - a) / a * 100, 2) if a else None,
                "cagr_pct": round(((i.value / a) ** (1 / n) - 1) * 100, 2)
                if a and a > 0 and i.value > 0 and n > 0
                else None,
            }
        )
    rows.sort(
        key=lambda r: r["pct_change"] if r["pct_change"] is not None else float("-inf"), reverse=order != "bottom"
    )
    for rank, r in enumerate(rows, 1):
        r["growth_rank"] = rank
    return {
        "indicator": indicator,
        "level": level,
        "year_from": year_from,
        "year_to": end.year,
        "territories_total": len(rows),
        "items": rows[: max(1, min(limit or 20, 60))],
        "meta": _meta(end.meta),
    }


def tool_compare_territories(
    db: Session, level: str, soatos: list[str], indicators: list[str], year: int | None = None
) -> dict:
    wanted = set(soatos[:15])
    out: dict[str, dict[str, Any]] = {}
    years: dict[str, int] = {}
    metas = {}
    for code in indicators[:6]:
        try:
            r = stats.get_ranking(db, code, level, year)  # type: ignore[arg-type]
        except stats.NotFoundError as e:
            out.setdefault("_errors", {})[code] = str(e)
            continue
        years[code] = r.year
        metas[code] = _meta(r.meta)
        for i in r.items:
            if i.soato in wanted:
                row = out.setdefault(i.soato, {"name": i.name})
                row[code] = i.value
                row[f"{code}_rank"] = f"{i.rank}/{len(r.items)}"
    # per-capita values computed here, never by the model
    try:
        pop = stats.get_ranking(db, "population_total", level, year)  # type: ignore[arg-type]
        pop_by = {i.soato: i.value for i in pop.items}
        additive = {i.code for i in stats.list_indicators(db) if i.additive and i.unit != "persons"}
        for soato, row in out.items():
            if soato.startswith("_") or soato not in pop_by or not pop_by[soato]:
                continue
            for code in indicators:
                if code in additive and code in row:
                    row[f"{code}_per_1000_people"] = round(row[code] / pop_by[soato] * 1000, 2)
        years["population_total"] = pop.year
    except stats.NotFoundError:
        pass
    missing = sorted(wanted - set(out))
    return {"level": level, "years_used": years, "territories": out, "not_found": missing, "meta": metas}


def tool_list_districts(db: Session, region: str) -> dict:
    return {
        "region": region,
        "districts": [{"soato": d.soato, "name": d.name_en, "kind": d.kind} for d in stats.list_districts(db, region)],
    }


def tool_get_overview(db: Session) -> dict:
    o = stats.get_overview(db)
    return {
        "kpis": [k.model_dump() for k in o.kpis],
        "regions": o.regions,
        "districts": o.districts,
        "cities": o.cities,
        "source": "SIAT (siat.stat.uz)",
    }


def tool_find_territory(db: Session, query: str) -> dict:
    matches = stats.find_territory(db, query, limit=5)
    if not matches:
        return {"error": "not_found", "message": f"No territory matches '{query}'"}
    return {"query": query, "matches": [m.model_dump() for m in matches]}


def tool_calculate_business_score(
    db: Session,
    business_type: str,
    region: str | None = None,
    level: str | None = None,
    target: str | None = None,
    budget_uzs: int | None = None,
    limit: int = 5,
) -> dict:
    req = recommendations.RecommendRequest(
        business_type=business_type,
        region=region,
        level=level,  # type: ignore[arg-type]
        target=target,  # type: ignore[arg-type]
        budget_uzs=budget_uzs,
        limit=max(1, min(limit or 5, 15)),
    )
    res = recommendations.recommend(db, req)
    for r in res["results"]:  # keep the context small: one source list per factor is enough
        for b in r["breakdown"]:
            b["sources"] = [{"dataset_id": x["dataset_id"], "url": x["url"]} for x in b["sources"][:2]]
    res["excluded_insufficient_data"] = [e["entity"]["name"] for e in res["excluded_insufficient_data"]]
    return res


def tool_forecast_indicator(db: Session, indicator: str, level: str, soato: str, horizon: int = 3) -> dict:
    f = forecasts.get_forecast(db, indicator, level, soato, max(1, min(horizon or 3, 3)))
    out = f.model_dump(mode="json")
    out["history"] = out["history"][-6:]
    return out


def tool_retrieve_documents(db: Session, query: str, k: int = 4) -> dict:
    return documents.retrieve_documents(db, query, k)


TOOL_FUNCS: dict[str, Callable[..., dict]] = {
    "get_ranking": tool_get_ranking,
    "get_timeseries": tool_get_timeseries,
    "compute_change": tool_compute_change,
    "get_growth_ranking": tool_get_growth_ranking,
    "compare_territories": tool_compare_territories,
    "list_districts": tool_list_districts,
    "get_overview": tool_get_overview,
    "find_territory": tool_find_territory,
    "calculate_business_score": tool_calculate_business_score,
    "forecast_indicator": tool_forecast_indicator,
    "retrieve_documents": tool_retrieve_documents,
}


def run_tool(db: Session, name: str, args: dict) -> dict:
    fn = TOOL_FUNCS.get(name)
    if fn is None:
        return {"error": f"unknown tool {name}"}
    try:
        return fn(db, **args)
    except stats.NotFoundError as e:
        return {"error": "not_found", "message": str(e)}
    except (TypeError, ValueError) as e:
        return {"error": "bad_arguments", "message": str(e)}


UZ_MARKERS = (
    "o‘",
    "o'",
    "g‘",
    "g'",
    "oʻ",
    "gʻ",
    "qaysi",
    "viloyat",
    "tuman",
    "qanday",
    "nechta",
    "uchun",
    "eng ",
    "bo‘yicha",
    "bo'yicha",
    "ochish",
    "qil",
    "haqida",
    "yil",
    "qancha",
    "shahri",
    "shahar",
    "aholi",
    "bo‘ladi",
    "bo'ladi",
    "kerak",
    "yaxshi",
    "qayer",
    "korxona",
    "nima",
)
LANG_NAMES = {"uz": "Uzbek (Latin script)", "ru": "Russian", "en": "English"}


def detect_language(text: str) -> str:
    """Cheap, deterministic language guess for the reply language (uz / ru / en)."""
    t = text.lower()
    letters = [c for c in t if c.isalpha()]
    if letters and sum("а" <= c <= "я" or c == "ё" for c in letters) / len(letters) > 0.3:
        return "ru"
    if sum(m in t for m in UZ_MARKERS) >= 2:
        return "uz"
    return "en"


def build_system_prompt(db: Session) -> str:
    inds = "\n".join(
        f"- {i.code}: {i.name_en} [{i.unit}; levels: {', '.join(i.levels)}; years {i.year_min}–{i.year_max}]"
        + (" (new, auto-added: mention that it was added automatically)" if i.auto_added else "")
        for i in stats.list_indicators(db)
    )
    regs = "\n".join(f"- {r.soato}: {r.name_en} / {r.name_uz}" for r in stats.list_regions(db))
    bts = ", ".join(b.business_type for b in recommendations.list_business_types())
    return SYSTEM_PROMPT.format(
        insufficient=INSUFFICIENT,
        indicators=inds,
        regions=regs,
        business_types=bts,
        disclaimer=recommendations.engine.DISCLAIMER,
    )


# --- streaming agent loop --------------------------------------------------------------------

# USD per 1M tokens (input, output) for the cost estimate; unknown models use the mini price.
PRICES = {
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-5": (1.25, 10.00),
    "gpt-5-mini": (0.25, 2.00),
}


def sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def map_focus(calls: list[tuple[str, dict, dict]]) -> dict | None:
    """Territories the answer is about, for the map (last tool with territories wins)."""
    for name, _, res in reversed(calls):
        if "error" in res:
            continue
        if name == "calculate_business_score":
            items = [r["entity"] for r in res.get("results", [])[:5]]
            return {
                "level": res["scope"]["level"],
                "soatos": [e["soato"] for e in items],
                "region": res["scope"].get("region_soato"),
            }
        if name in ("get_ranking", "get_growth_ranking"):
            return {"level": res["level"], "soatos": [i["soato"] for i in res.get("items", [])[:5]]}
        if name == "forecast_indicator" and res.get("level") != "country":
            return {"level": res["level"], "soatos": [res["soato"]]}
        if name == "compare_territories":
            return {"level": res["level"], "soatos": [k for k in res.get("territories", {}) if not k.startswith("_")]}
    return None


class RunLog:
    """Collects one agent run and writes it to agent_runs / agent_tool_calls + Prometheus."""

    def __init__(self, question: str, lang: str, mode: str, model: str | None) -> None:
        self.t0 = time.perf_counter()
        self.request_id = uuid.uuid4().hex
        self.question, self.lang, self.mode, self.model = question, lang, mode, model
        self.intent: str | None = None
        self.calls: list[tuple[str, dict, dict]] = []
        self.call_ms: list[int] = []
        self.tokens_in = self.tokens_out = 0
        self.answer = ""
        self.status = "ok"
        self.unsupported: list[str] = []

    def tool(self, db: Session, name: str, args: dict) -> dict:
        t = time.perf_counter()
        result = run_tool(db, name, args)
        dt = time.perf_counter() - t
        ok = "error" not in result
        self.calls.append((name, args, result))
        self.call_ms.append(int(dt * 1000))
        metrics.AGENT_TOOL_CALLS.labels(name, "ok" if ok else "error").inc()
        metrics.AGENT_TOOL_LATENCY.labels(name).observe(dt)
        return result

    def finish(self, db: Session) -> None:
        latency = time.perf_counter() - self.t0
        cost = 0.0
        if self.model:
            pin, pout = PRICES.get(self.model, PRICES["gpt-4.1-mini"])
            cost = (self.tokens_in * pin + self.tokens_out * pout) / 1e6
            metrics.AGENT_TOKENS.labels("input", self.model).inc(self.tokens_in)
            metrics.AGENT_TOKENS.labels("output", self.model).inc(self.tokens_out)
            metrics.AGENT_COST.labels(self.model).inc(cost)
        if self.unsupported:
            metrics.AGENT_VERIFICATION_FAILURES.inc(len(self.unsupported))
        if self.status == "ok" and INSUFFICIENT[:30] in self.answer:
            self.status = "insufficient"
        metrics.AGENT_REQUESTS.labels(self.intent or "llm", self.status, self.lang).inc()
        metrics.AGENT_LATENCY.labels(self.mode).observe(latency)
        try:
            run = AgentRun(
                request_id=self.request_id,
                question=self.question[:4000],
                lang=self.lang,
                intent=self.intent,
                mode=self.mode,
                model=self.model,
                status=self.status,
                latency_ms=int(latency * 1000),
                tokens_in=self.tokens_in,
                tokens_out=self.tokens_out,
                cost_usd=cost,
                tool_count=len(self.calls),
                verification_failures=len(self.unsupported),
                answer=self.answer[:20000],
            )
            db.add(run)
            db.flush()
            for (name, args, res), ms in zip(self.calls, self.call_ms, strict=True):
                db.add(AgentToolCall(run_id=run.id, name=name, args=args, ok="error" not in res, latency_ms=ms))
            db.commit()
        except Exception as e:  # logging must never break the chat
            db.rollback()
            log.warning("agent_run_log_failed", error=type(e).__name__)


def _final_events(run: RunLog, question: str) -> Iterator[str]:
    v = verify_answer(run.answer, [r for _, _, r in run.calls], question)
    run.unsupported = v["unsupported"]
    yield sse("verification", v)
    focus = map_focus(run.calls)
    reco = next((r for n, _, r in reversed(run.calls) if n == "calculate_business_score" and "error" not in r), None)
    yield sse(
        "result",
        {
            "request_id": run.request_id,
            "map_focus": focus,
            "recommendation": {"business_type": reco["business_type"], "region": reco["scope"].get("region_soato")}
            if reco
            else None,
            "is_synthetic": any(
                isinstance(r, dict) and (r.get("data_mode") == "demo" or r.get("meta", {}).get("is_synthetic"))
                for _, _, r in run.calls
            ),
        },
    )


def stream_fallback(messages: list[dict[str, str]]) -> Iterator[str]:
    """Rule-based agent: intent → fixed plan → tools → templated answer (no LLM)."""
    question = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
    lang = detect_language(question)
    run = RunLog(question, lang, "fallback", None)
    with get_sessionmaker()() as db:
        try:
            it = agent_fallback.parse_intent(db, question, lang)
            run.intent = it.intent
            for name, args in agent_fallback.plan(db, it):
                yield sse("tool_call", {"name": name, "label": TOOL_LABELS.get(name, name), "args": args})
                res = run.tool(db, name, args)
                yield sse("tool_result", {"name": name, "ok": "error" not in res})
            run.answer = agent_fallback.render(it, run.calls)
            for line in run.answer.splitlines(keepends=True):
                yield sse("token", {"text": line})
            yield from _final_events(run, question)
            yield sse("done", {"tools": [c[0] for c in run.calls], "mode": "fallback"})
        except Exception as e:
            run.status = "error"
            log.warning("fallback_error", error=type(e).__name__, detail=str(e)[:200])
            yield sse("error", {"message": f"Agent error: {type(e).__name__}."})
        finally:
            run.finish(db)


def stream_chat(messages: list[dict[str, str]]) -> Iterator[str]:
    """Yield SSE events: tool_call, tool_result, token, verification, result, done, error."""
    settings = get_settings()
    if not settings.openai_api_key:
        yield from stream_fallback(messages)
        return
    client = OpenAI(api_key=settings.openai_api_key)
    last_user = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
    lang_code = detect_language(last_user)
    run = RunLog(last_user, lang_code, "llm", settings.openai_model)

    with get_sessionmaker()() as db:
        convo: list[dict[str, Any]] = [{"role": "system", "content": build_system_prompt(db)}]
        convo += [
            {"role": m["role"], "content": m["content"]}
            for m in messages[-20:]
            if m.get("role") in ("user", "assistant") and m.get("content")
        ]
        lang = LANG_NAMES[lang_code]
        convo.append({"role": "system", "content": f"Write the whole answer in {lang}, including section headings."})
        try:
            for _ in range(MAX_TOOL_ROUNDS + 1):
                stream = client.chat.completions.create(
                    model=settings.openai_model,
                    messages=convo,
                    tools=TOOLS,
                    temperature=0.2,
                    stream=True,
                    stream_options={"include_usage": True},
                )
                content, calls = "", {}
                for chunk in stream:
                    if getattr(chunk, "usage", None):
                        run.tokens_in += chunk.usage.prompt_tokens or 0
                        run.tokens_out += chunk.usage.completion_tokens or 0
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    if delta.content:
                        content += delta.content
                        yield sse("token", {"text": delta.content})
                    for tc in delta.tool_calls or []:
                        c = calls.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
                        c["id"] = tc.id or c["id"]
                        if tc.function and tc.function.name:
                            c["name"] += tc.function.name
                        if tc.function and tc.function.arguments:
                            c["arguments"] += tc.function.arguments
                if not calls:
                    run.answer += content
                    break
                convo.append(
                    {
                        "role": "assistant",
                        "content": content or None,
                        "tool_calls": [
                            {
                                "id": c["id"],
                                "type": "function",
                                "function": {"name": c["name"], "arguments": c["arguments"]},
                            }
                            for c in calls.values()
                        ],
                    }
                )
                for c in calls.values():
                    try:
                        args = json.loads(c["arguments"] or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    yield sse(
                        "tool_call", {"name": c["name"], "label": TOOL_LABELS.get(c["name"], c["name"]), "args": args}
                    )
                    result = run.tool(db, c["name"], args)
                    yield sse("tool_result", {"name": c["name"], "ok": "error" not in result})
                    convo.append(
                        {
                            "role": "tool",
                            "tool_call_id": c["id"],
                            "content": json.dumps(result, ensure_ascii=False, default=str),
                        }
                    )
            else:
                yield sse("token", {"text": "\n\n_(Stopped: too many tool calls.)_"})
            run.intent = run.calls[-1][0] if run.calls else "chat"
            yield from _final_events(run, last_user)
            log.info("chat_done", tools=[c[0] for c in run.calls], unsupported=len(run.unsupported))
            yield sse("done", {"tools": [c[0] for c in run.calls], "mode": "llm"})
        except Exception as e:  # surface API errors to the UI without leaking secrets
            run.status = "error"
            log.warning("chat_error", error=type(e).__name__)
            yield sse("error", {"message": f"AI service error: {type(e).__name__}. Please try again."})
        finally:
            run.finish(db)
