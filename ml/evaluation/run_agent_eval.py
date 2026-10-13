"""Agent evaluation: tool selection, language, insufficient-data detection, numeric faithfulness, latency, cost."""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AgentRun
from app.services import chat

CASES = Path(__file__).resolve().parents[2] / "tests" / "eval" / "agent_cases.yaml"
# Words that only appear in Uzbek (Latin) answers, including the agents' section headings.
UZ_WORDS = (
    "o‘",
    "g‘",
    "oʻ",
    "gʻ",
    "rasmiy",
    "manbalar",
    "bashorat",
    "talqin",
    "aholi",
    "kishi",
    "yil",
    "tuman",
    "viloyat",
)


def answer_language(text: str) -> str:
    """Language of an answer. Answers are long and mix in proper names / tables, so this differs from
    chat.detect_language (built for short questions): any clear Uzbek marker or ≥ 15 % Cyrillic decides."""
    letters = [c for c in text.lower() if c.isalpha()]
    if letters and sum("а" <= c <= "я" or c == "ё" for c in letters) / len(letters) > 0.15:
        return "ru"
    low = text.lower()
    return "uz" if any(w in low for w in UZ_WORDS) else "en"


def _run_case(question: str) -> dict:
    tools, text, verification, result, error = [], [], None, None, None
    t0 = time.perf_counter()
    for block in chat.stream_chat([{"role": "user", "content": question}]):
        head, data = block.strip().split("\n", 1)
        event, payload = head[7:], json.loads(data[6:])
        if event == "tool_call":
            tools.append(payload["name"])
        elif event == "token":
            text.append(payload["text"])
        elif event == "verification":
            verification = payload
        elif event == "result":
            result = payload
        elif event == "error":
            error = payload["message"]
    return {
        "tools": tools,
        "answer": "".join(text),
        "verification": verification or {"checked": 0, "unsupported": []},
        "request_id": (result or {}).get("request_id"),
        "latency_s": time.perf_counter() - t0,
        "error": error,
    }


def run(db: Session, mode: str) -> dict:
    """mode: 'llm' or 'fallback' — the caller sets OPENAI_API_KEY accordingly."""
    cases = yaml.safe_load(CASES.read_text(encoding="utf-8"))["cases"]
    rows = []
    for c in cases:
        r = _run_case(c["question"])
        expected = set(c.get("expect_tools") or [])
        tool_ok = bool(expected & set(r["tools"])) if expected else not r["tools"]
        insufficient = chat.INSUFFICIENT[:40] in r["answer"] or "yetarli rasmiy" in r["answer"]
        insuff_ok = insufficient == bool(c.get("expect_insufficient", False))
        lang_ok = answer_language(r["answer"]) == c["expect_lang"] if r["answer"] else False
        faithful = not r["verification"]["unsupported"]
        run_row = db.scalar(select(AgentRun).where(AgentRun.request_id == r["request_id"])) if r["request_id"] else None
        rows.append(
            {
                "id": c["id"],
                "tools": r["tools"],
                "tool_ok": tool_ok,
                "lang_ok": lang_ok,
                "insufficient_ok": insuff_ok,
                "faithful": faithful,
                "unsupported": r["verification"]["unsupported"],
                "success": tool_ok and lang_ok and insuff_ok and faithful and not r["error"],
                "latency_s": r["latency_s"],
                "tokens": (run_row.tokens_in + run_row.tokens_out) if run_row else 0,
                "cost_usd": run_row.cost_usd if run_row else 0.0,
                "error": r["error"],
            }
        )
    n = len(rows)
    return {
        "mode": mode,
        "n_cases": n,
        "tool_selection_accuracy": sum(r["tool_ok"] for r in rows) / n,
        "language_accuracy": sum(r["lang_ok"] for r in rows) / n,
        "insufficient_detection_accuracy": sum(r["insufficient_ok"] for r in rows) / n,
        "numeric_faithfulness": sum(r["faithful"] for r in rows) / n,
        "task_success": sum(r["success"] for r in rows) / n,
        "latency_p50_s": float(np.percentile([r["latency_s"] for r in rows], 50)),
        "latency_p95_s": float(np.percentile([r["latency_s"] for r in rows], 95)),
        "tokens_total": int(sum(r["tokens"] for r in rows)),
        "cost_usd_total": float(sum(r["cost_usd"] for r in rows)),
        "cases": rows,
    }
