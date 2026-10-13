"""Per-IP rate limiting (slowapi). /chat is limited to 20 requests per minute (PLAN.md Phase 6)."""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

CHAT_LIMIT = "20/minute"
limiter = Limiter(key_func=get_remote_address)
