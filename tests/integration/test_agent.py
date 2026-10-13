"""Agent tests (PLAN.md Phase 8) with a scripted fake OpenAI client and the rule-based fallback.

Run against the local warehouse; skipped when it is not loaded.
"""

from __future__ import annotations

import json
from types import SimpleNamespace as NS
from typing import Any

import pytest

from app.core.config import get_settings
from app.services import chat
from tests.conftest import requires_db

pytestmark = requires_db


def events(stream) -> list[tuple[str, Any]]:  # noqa: ANN001
    out = []
    for block in stream:
        head, data = block.strip().split("\n", 1)
        out.append((head[7:], json.loads(data[6:])))
    return out


def text_of(evts: list[tuple[str, Any]]) -> str:
    return "".join(d["text"] for e, d in evts if e == "token")


class FakeOpenAI:
    """Replays scripted turns: each turn is either a tool call or a final text answer."""

    calls: list[dict] = []

    def __init__(self, script: list[dict]) -> None:
        self.script = script
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, **kwargs: Any):  # noqa: ANN202
        FakeOpenAI.calls.append(kwargs)
        turn = self.script.pop(0)
        if "tool" in turn:
            tc = NS(
                index=0,
                id="call_1",
                function=NS(name=turn["tool"], arguments=json.dumps(turn["args"])),
            )
            chunks = [NS(choices=[NS(delta=NS(content=None, tool_calls=[tc]))], usage=None)]
        else:
            chunks = [NS(choices=[NS(delta=NS(content=turn["text"], tool_calls=None))], usage=None)]
        chunks.append(NS(choices=[], usage=NS(prompt_tokens=100, completion_tokens=20)))
        return iter(chunks)


@pytest.fixture
def fake_llm(monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    get_settings.cache_clear()
    FakeOpenAI.calls = []

    def install(script: list[dict]) -> None:
        monkeypatch.setattr(chat, "OpenAI", lambda api_key: FakeOpenAI(script))

    yield install
    get_settings.cache_clear()


def test_bakery_question_calls_business_score(fake_llm) -> None:  # noqa: ANN001
    fake_llm(
        [
            {"tool": "calculate_business_score", "args": {"business_type": "bakery", "region": "1730"}},
            {"text": "**Model prediction** Fergana city ranks first."},
        ]
    )
    evts = events(chat.stream_chat([{"role": "user", "content": "Where should I open a bakery in Fergana?"}]))
    tools = [d["name"] for e, d in evts if e == "tool_call"]
    assert tools == ["calculate_business_score"]
    result = next(d for e, d in evts if e == "result")
    assert result["map_focus"]["level"] == "district" and len(result["map_focus"]["soatos"]) == 5
    assert ("done", {"tools": ["calculate_business_score"], "mode": "llm"}) in evts


def test_verifier_catches_invented_number(fake_llm) -> None:  # noqa: ANN001
    fake_llm(
        [
            {"tool": "get_timeseries", "args": {"indicator": "population_total", "level": "region", "soato": "1730"}},
            {"text": "Fergana region has 9.87 million people."},  # not in any tool result
        ]
    )
    evts = events(chat.stream_chat([{"role": "user", "content": "Population of Fergana region?"}]))
    v = next(d for e, d in evts if e == "verification")
    assert v["unsupported"] == ["9.87"]


def test_reply_language_instruction_follows_question(fake_llm) -> None:  # noqa: ANN001
    fake_llm([{"text": "Javob."}])
    events(chat.stream_chat([{"role": "user", "content": "Farg‘ona viloyatida qaysi tumanlarda aholi ko‘p?"}]))
    system = [m["content"] for m in FakeOpenAI.calls[0]["messages"] if m["role"] == "system"]
    assert any("Uzbek" in s for s in system)


def test_fallback_works_without_key(no_openai_key) -> None:  # noqa: ANN001
    evts = events(chat.stream_chat([{"role": "user", "content": "Where should I open a bakery in Fergana region?"}]))
    assert [d["name"] for e, d in evts if e == "tool_call"] == ["calculate_business_score"]
    assert "Business Opportunity Score" in text_of(evts)
    assert next(d for e, d in evts if e == "verification")["unsupported"] == []


def test_no_data_question_gets_insufficient_sentence(no_openai_key) -> None:  # noqa: ANN001
    evts = events(chat.stream_chat([{"role": "user", "content": "What is the average salary in Chilanzar district?"}]))
    assert "I don't have sufficient official data to answer this reliably." in text_of(evts)


@pytest.mark.parametrize(
    ("question", "heading"),
    [
        ("Farg‘ona viloyatida dorixona ochish uchun eng yaxshi tuman qaysi?", "Model bashorati"),
        ("Где в Самаркандской области лучше открыть кафе?", "Прогноз модели"),
    ],
)
def test_uzbek_and_russian_answers_stay_in_language(no_openai_key, question: str, heading: str) -> None:  # noqa: ANN001
    assert heading in text_of(events(chat.stream_chat([{"role": "user", "content": question}])))
