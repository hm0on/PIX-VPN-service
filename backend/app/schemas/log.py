"""Log schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class BotLogCreate(BaseModel):
    level: int = Field(ge=0, le=2, default=0)
    event: str = Field(min_length=1, max_length=128)
    module: str = Field(default="bot", max_length=64)
    user_id: int | None = None
    message: str = Field(default="", max_length=8000)
    context: dict[str, Any] | None = None


class TechLogCreate(BaseModel):
    trace_id: str | None = Field(default=None, max_length=36)
    service: str = Field(default="bot", max_length=32)
    action: str = Field(min_length=1, max_length=128)
    user_id: int | None = None
    payload: dict[str, Any] | None = None
    duration_ms: int | None = None
