"""Admin Logs schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AdminLogItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    level: int
    event: str
    module: str
    user_id: int | None = None
    message: str
    context: dict[str, Any] | None = None
    created_at: datetime


class AdminLogsPage(BaseModel):
    items: list[AdminLogItem]
    next_before_id: int | None = None
    total: int | None = None


class AdminTechLogItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    trace_id: str
    service: str
    action: str
    user_id: int | None = None
    payload: dict[str, Any] | None = None
    duration_ms: int | None = None
    created_at: datetime


class AdminTechLogsPage(BaseModel):
    items: list[AdminTechLogItem]
    next_before_id: int | None = None
    total: int | None = None
