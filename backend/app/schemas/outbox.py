"""Schemas for outbox API (worker <-> backend)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class OutboxMessageResponse(ORMModel):
    id: int
    user_id: int
    chat_id: int
    message_type: str
    payload: dict[str, Any]
    status: str
    attempts: int
    last_error: str | None = None
    send_after: datetime
    sent_at: datetime | None = None
    created_at: datetime


class OutboxPendingResponse(BaseModel):
    items: list[OutboxMessageResponse]


class OutboxSentRequest(BaseModel):
    tg_message_id: int | None = None


class OutboxFailedRequest(BaseModel):
    error: str = Field(..., max_length=2048)


class OutboxAckResponse(BaseModel):
    ok: bool = True
    status: str
