"""AI analyst chat: OpenAI tool-calling over the official-statistics services.

Rules enforced here (CLAUDE.md):
- The LLM never computes numbers: every figure (values, shares, growth, CAGR, comparisons) comes from a tool.
- No invented statistics: when tools return nothing, the model must say data is insufficient.
- Answers separate "Official statistics" from "AI interpretation" and cite SIAT sources.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from typing import Any

from openai import OpenAI
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.session import get_sessionmaker
from app.services import statistics as stats

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
2. If the tools return no data for the question, say exactly: "{insufficient}" (translated into the user's
   language) and explain what data is missing. Never fill gaps with general knowledge numbers.
3. Reply in the user's language (Uzbek, Russian or English) — match the language of the last user message.
   For Uzbek use Latin script.
4. Structure every analytical answer with these sections (translated headings):
   **Official statistics** — the figures from tools, with year and unit.
   **AI interpretation** — your reasoning, clearly labelled as interpretation, not fact.
   **Sources** — SIAT dataset ids/links from the tool `meta`.
   Short factual questions may use a compact form, but always name the year and source.
5. Units: values are already converted — persons (not thousands), UZS (not billions). Present large numbers
   readably (e.g. "4.38 million people", "397.4 trillion UZS"). Growth indicators named "...growth"
   are "% of previous year" (112.3 means +12.3%).
6. There is NO official district-level income or wage data in this system. Say so if asked.
7. Use markdown: short paragraphs, bullet lists, and small tables for rankings.
8. Method: for "fastest growing / grew most / o'sish / рост" questions ALWAYS call `get_growth_ranking`
   (it ranks every territory by growth in one call) — never pick territories by size first.
   Use the latest available year unless the user names one. For "best place to open X" questions,
   look at size (population), growth, and the relevant sector volume/per-capita values, then compare.

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
]

TOOL_LABELS = {
    "get_ranking": "Ranking territories",
    "get_timeseries": "Loading history",
    "compute_change": "Computing growth",
    "get_growth_ranking": "Ranking by growth",
    "compare_territories": "Comparing territories",
    "list_districts": "Listing districts",
    "get_overview": "Loading national KPIs",
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


TOOL_FUNCS: dict[str, Callable[..., dict]] = {
    "get_ranking": tool_get_ranking,
    "get_timeseries": tool_get_timeseries,
    "compute_change": tool_compute_change,
    "get_growth_ranking": tool_get_growth_ranking,
    "compare_territories": tool_compare_territories,
    "list_districts": tool_list_districts,
    "get_overview": tool_get_overview,
}


def run_tool(db: Session, name: str, args: dict) -> dict:
    fn = TOOL_FUNCS.get(name)
    if fn is None:
        return {"error": f"unknown tool {name}"}
    try:
        return fn(db, **args)
    except stats.NotFoundError as e:
        return {"error": "not_found", "message": str(e)}
    except TypeError as e:
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
    "ber",
    "haqida",
    "yil",
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
        for i in stats.list_indicators(db)
    )
    regs = "\n".join(f"- {r.soato}: {r.name_en} / {r.name_uz}" for r in stats.list_regions(db))
    return SYSTEM_PROMPT.format(insufficient=INSUFFICIENT, indicators=inds, regions=regs)


# --- streaming agent loop --------------------------------------------------------------------


def sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def stream_chat(messages: list[dict[str, str]]) -> Iterator[str]:
    """Yield SSE events: tool_call, tool_result, token, done, error."""
    settings = get_settings()
    if not settings.openai_api_key:
        yield sse("error", {"message": "OPENAI_API_KEY is not set — add it to .env to enable the AI analyst."})
        return
    client = OpenAI(api_key=settings.openai_api_key)

    with get_sessionmaker()() as db:
        convo: list[dict[str, Any]] = [{"role": "system", "content": build_system_prompt(db)}]
        convo += [
            {"role": m["role"], "content": m["content"]}
            for m in messages[-20:]
            if m.get("role") in ("user", "assistant") and m.get("content")
        ]
        last_user = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
        lang = LANG_NAMES[detect_language(last_user)]
        convo.append({"role": "system", "content": f"Write the whole answer in {lang}, including section headings."})
        tools_used: list[str] = []
        try:
            for _ in range(MAX_TOOL_ROUNDS + 1):
                stream = client.chat.completions.create(
                    model=settings.openai_model,
                    messages=convo,
                    tools=TOOLS,
                    temperature=0.2,
                    stream=True,
                )
                content, calls = "", {}
                for chunk in stream:
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
                    result = run_tool(db, c["name"], args)
                    tools_used.append(c["name"])
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
            log.info("chat_done", tools=tools_used)
            yield sse("done", {"tools": tools_used})
        except Exception as e:  # surface API errors to the UI without leaking secrets
            log.warning("chat_error", error=type(e).__name__)
            yield sse("error", {"message": f"AI service error: {type(e).__name__}. Please try again."})
