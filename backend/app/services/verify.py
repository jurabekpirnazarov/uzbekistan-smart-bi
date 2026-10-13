"""Numeric faithfulness check (PLAN.md Phase 8 step 4).

Every number in the answer must be supported by a tool result: equal within rounding, possibly
re-scaled for display (thousand / million / billion / trillion, rate → %, % → index). Years, small
counting numbers and numbers that the user wrote themselves are not checked.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from typing import Any

# 4,382,100 · 4 382 100 · 4.38 · 12,5 · -3.2 · 1.2e6
NUMBER = re.compile(
    r"(?<![\w.])[-−]?\d{1,3}(?:[ ,  ]\d{3})+(?:[.,]\d+)?(?![\d])|(?<![\w.])[-−]?\d+(?:[.,]\d+)?(?![\d])"
)
SCALES = (1.0, 1e3, 1e6, 1e9, 1e12, 1e15, 1e-2, 1e2)
REL_TOL = 0.02  # display rounding (e.g. 4.38 million for 4,382,100 → 0.05 %; 4.4 million → 0.4 %)
SKIP_SMALL_INT = 10


def parse_number(token: str) -> float | None:
    t = token.replace("−", "-").replace(" ", " ").replace(" ", " ")
    if re.search(r"\d[ ,]\d{3}(?:\D|$)", t) and t.count(",") + t.count(" ") >= 1:
        # thousands separators; a trailing ",d" or ".d" with != 3 digits is a decimal part
        m = re.match(r"^(-?[\d ,]+?)(?:[.,](\d{1,2}|\d{4,}))?$", t)
        if m:
            whole = m.group(1).replace(" ", "").replace(",", "")
            frac = m.group(2)
            try:
                return float(f"{whole}.{frac}") if frac else float(whole)
            except ValueError:
                return None
    try:
        return float(t.replace(",", "."))
    except ValueError:
        return None


# "80% interval", "80% ishonch oralig‘i", "95% доверительный интервал" are labels, not claims
INTERVAL_LABEL = re.compile(
    r"(?<!\d)(?:80|95)\s?%[^.\n\d]{0,30}?(?:interval|oraliq|oralig|интервал|ishonch|confidence|довери|ДИ|CI)",
    re.IGNORECASE,
)
# "SIAT 246", "SIAT datasets 4470, 4471", "dataset id 1362" are citations, not claims
CITATION = re.compile(r"\b(?:siat|datasets?|dataset id)\b[\s#:]*\d+(?:\s*(?:,|and|va|и)\s*\d+)*", re.IGNORECASE)
# "per 1,000 people", "10,000 kishiga", "на 1000 жителей" are units of a rate, not claims
_ROUND = r"(?:1|10|100)(?:[ ,. ]?000)+"
PER_UNIT = re.compile(
    rf"(?:\b(?:per|на)\s*{_ROUND})|(?:\b{_ROUND}\s*(?:kishi|aholi|people|persons|inhabitants|жител|человек))",
    re.IGNORECASE,
)


def extract_numbers(text: str) -> list[tuple[str, float]]:
    # drop citations, interval labels, markdown links / URLs — none of them are claims
    clean = PER_UNIT.sub(" ", CITATION.sub(" ", text))
    clean = INTERVAL_LABEL.sub(" ", clean)
    clean = re.sub(r"\]\([^)]*\)", "]", clean)
    clean = re.sub(r"https?://\S+", "", clean)
    out = []
    for m in NUMBER.finditer(clean):
        v = parse_number(m.group(0).strip())
        if v is not None:
            out.append((m.group(0).strip(), v))
    return out


def numeric_leaves(obj: Any) -> Iterable[float]:
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, int | float):
        if math.isfinite(obj):
            yield float(obj)
    elif isinstance(obj, str):
        for _, v in extract_numbers(obj):
            yield v
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str) and k.isdigit():  # SOATO-keyed results: the code itself is a fact too
                yield float(k)
            yield from numeric_leaves(v)
    elif isinstance(obj, list | tuple):
        for v in obj:
            yield from numeric_leaves(v)


def _supported(x: float, refs: list[float]) -> bool:
    ax = abs(x)
    for r in refs:
        ar = abs(r)
        if ar == 0:
            if ax == 0:
                return True
            continue
        for s in SCALES:
            target = ar / s
            if target == 0:
                continue
            if abs(ax - target) <= max(REL_TOL * target, 0.051):  # ±0.05 for 1-decimal rounding
                return True
        # growth index ↔ percent change (112.3 ↔ 12.3 %) and rate ↔ percent (0.123 ↔ 12.3 %)
        for alt in (ar - 100, (ar - 1) * 100 if ar < 3 else None, ar * 100):
            if alt is not None and abs(ax - abs(alt)) <= max(REL_TOL * abs(alt), 0.051):
                return True
    return False


def verify_answer(answer: str, tool_results: list[Any], question: str = "") -> dict:
    """{'checked': n, 'unsupported': [tokens]} — unsupported numbers are possible hallucinations."""
    refs = sorted({v for r in tool_results for v in numeric_leaves(r)})
    asked = {v for _, v in extract_numbers(question)}
    checked, unsupported = 0, []
    for token, v in extract_numbers(answer):
        if float(v).is_integer() and (abs(v) <= SKIP_SMALL_INT or 1990 <= v <= 2100):
            continue  # list numbers, ranks, years
        if v in asked:
            continue
        checked += 1
        if not _supported(v, refs):
            unsupported.append(token)
    return {"checked": checked, "unsupported": unsupported}
