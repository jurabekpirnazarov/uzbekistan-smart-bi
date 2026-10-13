"""POST /chat — AI analyst over SSE.

Events: tool_call, tool_result, token, verification, result, done, error. Rate limited per IP.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.ratelimit import CHAT_LIMIT, limiter
from app.services.chat import stream_chat

router = APIRouter(tags=["chat"])


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=8000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=40)


@router.post("/chat")
@limiter.limit(CHAT_LIMIT)
def chat(request: Request, req: ChatRequest) -> StreamingResponse:
    return StreamingResponse(
        stream_chat([m.model_dump() for m in req.messages]),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/chat/status")
def chat_status() -> dict:
    s = get_settings()
    # Without a key the rule-based planner answers (CLAUDE.md rule 10), so the chat is always available.
    return {
        "enabled": True,
        "mode": "llm" if s.llm_enabled else "fallback",
        "model": s.openai_model if s.llm_enabled else None,
    }
