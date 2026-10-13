"""User feedback (👍/👎) on chat answers and recommendations."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core import metrics
from app.db.models import Feedback


class FeedbackIn(BaseModel):
    request_id: str | None = Field(default=None, max_length=64)
    target: Literal["chat", "recommendation"] = "chat"
    rating: Literal[1, -1]
    comment: str | None = Field(default=None, max_length=2000)


def save_feedback(db: Session, fb: FeedbackIn) -> dict:
    row = Feedback(request_id=fb.request_id, target=fb.target, rating=fb.rating, comment=fb.comment)
    db.add(row)
    db.commit()
    metrics.USER_FEEDBACK.labels("up" if fb.rating > 0 else "down").inc()
    return {"id": row.id, "status": "saved"}
