"""Rule-based agent used when OPENAI_API_KEY is not set (CLAUDE.md rule 10).

Keyword intent parser (en / uz / ru) → fixed tool plan per intent → templated answer with the same
layers as the LLM agent: Official statistics / Model prediction / Interpretation / Sources.
All numbers come from tool results; nothing is invented.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.services import statistics as stats
from ml.scoring.profiles import load_profiles

INSUFFICIENT = {
    "en": "I don't have sufficient official data to answer this reliably.",
    "uz": "Bu savolga ishonchli javob berish uchun yetarli rasmiy ma’lumot yo‘q.",
    "ru": "У меня недостаточно официальных данных, чтобы надёжно ответить на этот вопрос.",
}
H = {
    "en": {
        "stats": "Official statistics",
        "model": "Model prediction",
        "interp": "Interpretation (rule-based, no AI model configured)",
        "sources": "Sources",
        "score": "Business Opportunity Score",
        "rank": "Rank",
        "place": "Territory",
        "range": "Rank range",
        "drivers": "Main drivers",
        "year": "Year",
        "value": "Value",
        "forecast": "Forecast",
        "interval": "80% interval",
        "change": "Change",
    },
    "uz": {
        "stats": "Rasmiy statistika",
        "model": "Model bashorati",
        "interp": "Talqin (qoidaga asoslangan, AI modeli ulanmagan)",
        "sources": "Manbalar",
        "score": "Biznes imkoniyati balli",
        "rank": "O‘rin",
        "place": "Hudud",
        "range": "O‘rin oralig‘i",
        "drivers": "Asosiy omillar",
        "year": "Yil",
        "value": "Qiymat",
        "forecast": "Bashorat",
        "interval": "80% oraliq",
        "change": "O‘zgarish",
    },
    "ru": {
        "stats": "Официальная статистика",
        "model": "Прогноз модели",
        "interp": "Интерпретация (по правилам, AI-модель не подключена)",
        "sources": "Источники",
        "score": "Индекс бизнес-возможностей",
        "rank": "Место",
        "place": "Территория",
        "range": "Диапазон мест",
        "drivers": "Главные факторы",
        "year": "Год",
        "value": "Значение",
        "forecast": "Прогноз",
        "interval": "80% интервал",
        "change": "Изменение",
    },
}
SCALE_WORDS = {
    "en": ("thousand", "million", "billion", "trillion"),
    "uz": ("ming", "mln", "mlrd", "trln"),
    "ru": ("тыс.", "млн", "млрд", "трлн"),
}
UNIT_WORDS = {
    "en": {"persons": "people", "UZS": "UZS", "units": ""},
    "uz": {"persons": "kishi", "UZS": "so‘m", "units": "ta"},
    "ru": {"persons": "чел.", "UZS": "сум", "units": "ед."},
}

INTENT_WORDS = {
    "income": ["income", "wage", "salary", "daromad", "ish haqi", "maosh", "доход", "зарплат"],
    "methodology": [
        "methodolog", "how is", "how are", "defined", "definition", "how does the score", "how do you calculate",
        "metodolog", "qanday hisob", "nima degani", "методолог", "как рассчит", "как считает", "что такое",
    ],
    "forecast": ["forecast", "predict", "projection", "prognoz", "bashorat", "прогноз", "will be"],
    "compare": ["compare", " vs ", "versus", "solishtir", "taqqos", "сравн"],
    "recommend": [
        "open", "start a", "where should", "best place", "best district", "ochish", "ochmoqchi", "qayerda",
        "eng yaxshi", "открыть", "где лучше", "лучший район", "лучше открыть",
    ],
    "growth": ["fastest", "grew", "growing", "growth", "tez o", "o‘sish", "o'sish", "o‘sgan", "o'sgan", "рост", "быстрее", "вырос"],
}  # fmt: skip
INDICATOR_WORDS = [
    ("enterprises_new", ["new business", "new compan", "yangi korxona", "yangi tashkil", "новых предприят", "новые предприят"]),
    ("hospitals", ["hospital", "kasalxona", "shifoxona", "больниц"]),
    ("outpatient_clinics", ["polyclinic", "outpatient", "poliklinika", "поликлиник"]),
    ("trade_services_volume", ["trade", "savdo", "торгов"]),
    ("food_services_volume", ["food service", "catering", "umumiy ovqatlanish", "общепит", "питани"]),
    ("health_services_volume", ["health service", "sog‘liq", "sog'liq", "здравоохран"]),
    ("education_services_volume", ["education service", "ta’lim xizmat", "ta'lim xizmat", "образовательн"]),
    ("transport_services_volume", ["transport"]),
    ("market_services_volume", ["service", "xizmat", "услуг"]),
    ("enterprises_active", ["business", "compan", "enterprise", "firm", "korxona", "biznes", "tadbirkor", "предприят", "бизнес", "компани"]),
    ("population_total", ["population", "people", "aholi", "населен", "жител"]),
]  # fmt: skip


@dataclass
class Intent:
    intent: str
    lang: str
    business_type: str | None = None
    territories: list[stats.TerritoryMatch] = field(default_factory=list)
    indicator: str = "population_total"
    text: str = ""


def _has(text: str, words: list[str]) -> bool:
    return any(w in text for w in words)


REGION_WORDS = ("region", "province", "viloyat", "област", "вилоят", "respublika", "республик")


def find_territories(db: Session, text: str) -> list[stats.TerritoryMatch]:
    """Territories mentioned in the text: best fuzzy match per 1–3 word window (score ≥ 90).

    When the text says "region / viloyat / область", region-level names are matched first, so
    "Самаркандской области" resolves to Samarkand region, not Samarkand district.
    """
    if any(w in text.lower() for w in REGION_WORDS):
        regions = _find(db, text, "region", min_score=80)  # inflected forms ("Самаркандской") score lower
        if regions:
            return regions + [
                d for d in _find(db, text, "district") if d.region_soato not in {r.soato for r in regions}
            ]
    return _find(db, text, None)


def _find(db: Session, text: str, level: str | None, min_score: float = 90) -> list[stats.TerritoryMatch]:
    words = re.findall(r"[\w‘’ʻ'-]+", text)
    found: dict[str, stats.TerritoryMatch] = {}
    for n in (3, 2, 1):
        for i in range(len(words) - n + 1):
            chunk = " ".join(words[i : i + n])
            if len(chunk) < 4:
                continue
            for m in stats.find_territory(db, chunk, level=level, limit=1):  # type: ignore[arg-type]
                if m.score >= min_score and m.soato not in found:
                    # skip if a longer, already-found name covers it (e.g. "Fergana city" vs "Fergana")
                    if not any(m.name.split()[0] == f.name.split()[0] and f.score >= m.score for f in found.values()):
                        found[m.soato] = m
    return list(found.values())


def parse_intent(db: Session, text: str, lang: str) -> Intent:
    t = f" {text.lower()} "
    business = None
    for bt, p in load_profiles().items():
        if _has(t, [k.lower() for k in p.keywords]):
            business = bt
            break
    indicator = next((code for code, words in INDICATOR_WORDS if _has(t, words)), "population_total")
    territories = find_territories(db, text)
    if _has(t, INTENT_WORDS["income"]):
        intent = "income"
    elif _has(t, INTENT_WORDS["methodology"]):
        intent = "methodology"
    elif _has(t, INTENT_WORDS["forecast"]):
        intent = "forecast"
    elif _has(t, INTENT_WORDS["compare"]) and len(territories) >= 2:
        intent = "compare"
    elif business:  # a business type in the question means "where to open it"
        intent = "recommend"
    elif _has(t, INTENT_WORDS["growth"]):
        intent = "growth"
    else:
        intent = "statistic"
    return Intent(intent, lang, business, territories, indicator, text)


# --- formatting ------------------------------------------------------------------------------


def fmt(v: float | None, unit: str, lang: str) -> str:
    if v is None:
        return "—"
    words = SCALE_WORDS[lang]
    a = abs(v)
    for s, scale_word in ((1e12, words[3]), (1e9, words[2]), (1e6, words[1])):
        if a >= s:
            num, w = f"{v / s:,.2f}", scale_word
            break
    else:
        num, w = (f"{v:,.0f}" if a >= 100 or float(v).is_integer() else f"{v:,.2f}"), ""
    u = UNIT_WORDS[lang].get(unit, unit)
    return " ".join(x for x in (num, w, u) if x)


def _sources(results: list[dict]) -> list[str]:
    seen: dict[Any, str] = {}
    for r in results:
        for m in _walk_meta(r):
            sid = m.get("siat_dataset_id") or m.get("dataset_id")
            if sid and sid not in seen:
                seen[sid] = m.get("url") or f"https://siat.stat.uz (dataset {sid})"
    return [f"- SIAT dataset {k}: {u}" for k, u in seen.items()]


def _walk_meta(obj: Any) -> list[dict]:
    out = []
    if isinstance(obj, dict):
        if ("siat_dataset_id" in obj or "dataset_id" in obj) and ("url" in obj):
            out.append(obj)
        for v in obj.values():
            out += _walk_meta(v)
    elif isinstance(obj, list):
        for v in obj:
            out += _walk_meta(v)
    return out


# --- plans -------------------------------------------------------------------------------------


def plan(db: Session, it: Intent) -> list[tuple[str, dict]]:
    """Ordered tool calls for the intent (names match the LLM tool registry)."""
    region = next((t for t in it.territories if t.level == "region"), None)
    district = next((t for t in it.territories if t.level == "district"), None)
    if it.intent == "income":
        return []
    if it.intent == "methodology":
        return [("retrieve_documents", {"query": it.text, "k": 3})]
    if it.intent == "recommend":
        args: dict[str, Any] = {"business_type": it.business_type}
        r = region.soato if region else (district.region_soato if district else None)
        if r:
            args["region"] = r
        return [("calculate_business_score", args)]
    if it.intent == "forecast":
        t = district or region
        lv, soato = (t.level, t.soato) if t else ("country", "1700")
        return [("forecast_indicator", {"indicator": it.indicator, "level": lv, "soato": soato, "horizon": 3})]
    if it.intent == "compare":
        lv = "district" if all(t.level == "district" for t in it.territories) else "region"
        soatos = [t.soato if lv == t.level else (t.region_soato or t.soato) for t in it.territories][:6]
        inds = list(dict.fromkeys([it.indicator, "population_total", "enterprises_active"]))[:3]
        return [("compare_territories", {"level": lv, "soatos": soatos, "indicators": inds})]
    if it.intent == "growth":
        lv, reg = ("district", region.soato) if region else ("region", None)
        start = 2020 if it.indicator.endswith("_volume") else 2019
        a = {"indicator": it.indicator, "level": lv, "year_from": start, "limit": 5}
        if reg:
            a["region"] = reg
        return [("get_growth_ranking", a)]
    if district or region:
        t = district or region
        return [("get_timeseries", {"indicator": it.indicator, "level": t.level, "soato": t.soato})]
    return [("get_ranking", {"indicator": it.indicator, "level": "region", "limit": 5})]


# --- answers -----------------------------------------------------------------------------------


def render(it: Intent, calls: list[tuple[str, dict, dict]]) -> str:
    L, h = it.lang, H[it.lang]
    if it.intent == "income" or not calls or all("error" in r for _, _, r in calls):
        extra = {
            "en": "There is no official district-level income or wage data in this system.",
            "uz": "Tizimda tumanlar kesimida daromad yoki ish haqi bo‘yicha rasmiy ma’lumot yo‘q.",
            "ru": "В системе нет официальных данных о доходах или зарплатах по районам.",
        }[L]
        err = next((r.get("message") for _, _, r in calls if "error" in r), None)
        return f"{INSUFFICIENT[L]}\n\n{extra if it.intent == 'income' else (err or '')}".strip()
    name, args, res = calls[-1]
    out: list[str] = []
    if name == "calculate_business_score":
        bt = res["display_name"][L]
        out += [f"**{h['model']} — {h['score']}: {bt}**", ""]
        out += [
            f"| {h['rank']} | {h['place']} | {h['score']} | {h['range']} | {h['drivers']} |",
            "|---|---|---|---|---|",
        ]
        for r in res["results"][:5]:
            top = sorted(r["breakdown"], key=lambda b: -b["contribution"])[:2]
            drv = ", ".join(f"{b['label']} ({b['contribution']:.1f})" for b in top)
            out.append(
                f"| {r['rank']} | {r['entity']['name']} | {r['score']:.1f} | {r['rank_range'][0]}–{r['rank_range'][1]} | {drv} |"
            )
        out += ["", f"_{res['disclaimer']}_", "", f"**{h['interp']}**", ""]
        best = res["results"][0] if res["results"] else None
        if best:
            out.append(
                {
                    "en": f"{best['entity']['name']} ranks first among {res['scope']['ranked']} candidates. "
                    "The score is relative to the other territories in the scope and depends on the factor weights.",
                    "uz": f"{best['entity']['name']} {res['scope']['ranked']} ta hudud orasida birinchi o‘rinda. "
                    "Ball boshqa hududlarga nisbatan hisoblanadi va omillar vazniga bog‘liq.",
                    "ru": f"{best['entity']['name']} — первое место среди {res['scope']['ranked']} территорий. "
                    "Балл относителен к другим территориям и зависит от весов факторов.",
                }[L]
            )
    elif name == "forecast_indicator":
        unit = res.get("meta", {}).get("unit") or ""
        last = res["history"][-1] if res["history"] else None
        out += [f"**{h['stats']}** — {res['name']}", ""]
        if last:
            out.append(f"- {last['year']}: {fmt(last['value'], unit, L)}")
        out += [
            "",
            f"**{h['model']}** ({res['model']})",
            "",
            f"| {h['year']} | {h['forecast']} | {h['interval']} |",
            "|---|---|---|",
        ]
        for p in res["forecast"]:
            out.append(
                f"| {p['year']} | {fmt(p['yhat'], unit, L)} | {fmt(p['lo80'], unit, L)} – {fmt(p['hi80'], unit, L)} |"
            )
        out += ["", f"_{res['note']}_"]
    elif name == "compare_territories":
        out += [f"**{h['stats']}**", ""]
        inds = args["indicators"]
        out.append("| " + h["place"] + " | " + " | ".join(inds) + " |")
        out.append("|---" * (len(inds) + 1) + "|")
        for soato, row in res["territories"].items():
            if soato.startswith("_"):
                continue
            units = {c: (res.get("meta", {}).get(c) or {}).get("unit") or "" for c in inds}
            out.append("| " + row["name"] + " | " + " | ".join(fmt(row.get(c), units[c], L) for c in inds) + " |")
        out.append("")
        out.append(f"{h['year']}: " + ", ".join(f"{k} {v}" for k, v in res["years_used"].items()))
    elif name == "get_growth_ranking":
        unit = res.get("meta", {}).get("unit") or ""
        out += [f"**{h['stats']}** — {res['indicator']}, {res['year_from']}–{res['year_to']}", ""]
        out += [
            f"| {h['rank']} | {h['place']} | {res['year_from']} | {res['year_to']} | {h['change']} |",
            "|---|---|---|---|---|",
        ]
        for r in res["items"][:5]:
            out.append(
                f"| {r['growth_rank']} | {r['name']} | {fmt(r['value_from'], unit, L)} | {fmt(r['value_to'], unit, L)} | {r['pct_change']:+.1f}% |"
            )
    elif name == "get_ranking":
        unit = res.get("meta", {}).get("unit") or ""
        out += [f"**{h['stats']}** — {res['indicator']}, {res['year']}", ""]
        out += [f"| {h['rank']} | {h['place']} | {h['value']} |", "|---|---|---|"]
        for r in res["items"][:5]:
            out.append(f"| {r['rank']} | {r['name']} | {fmt(r['value'], unit, L)} |")
    elif name == "get_timeseries":
        unit = res.get("meta", {}).get("unit") or ""
        pts = res["points"][-5:]
        out += [f"**{h['stats']}** — {res['territory']}, {res['indicator']}", ""]
        out += [f"| {h['year']} | {h['value']} |", "|---|---|"] + [
            f"| {p['year']} | {fmt(p['value'], unit, L)} |" for p in pts
        ]
    elif name == "retrieve_documents":
        out += [f"**{h['sources']}**", ""]
        for d in res["results"][:3]:
            text = d["content"]
            # SIAT metadata documents: quote the methodology paragraph, not the multilingual header
            if "Methodology:" in text:
                text = text.split("Methodology:", 1)[1]
            snippet = " ".join(text.split())[:400]
            link = f" ([source]({d['source_url']}))" if (d.get("source_url") or "").startswith("http") else ""
            out.append(f"- **{d['title']}**{link} — {snippet}…")
    src = _sources([r for _, _, r in calls])
    if src:
        out += ["", f"**{h['sources']}**", *src]
    return "\n".join(out)
