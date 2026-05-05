"""Pydantic schemas for NorthLine API requests and responses."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class KeyResponse(BaseModel):
    ok: bool = True
    subscription_id: str
    key: str
    expires_at: datetime
    devices: int
    days: int


class ExtendResponse(BaseModel):
    ok: bool = True
    subscription_id: str
    expires_at: datetime
    added_days: int


class DeactivateResponse(BaseModel):
    ok: bool = True
    subscription_id: str
    deactivated_at: datetime


class KeyDevice(BaseModel):
    device_id: str
    name: str | None = None
    platform: str | None = None
    last_seen: datetime | None = None
    traffic_bytes: int | None = None


class KeyInfo(BaseModel):
    ok: bool = True
    subscription_id: str
    key: str
    status: str
    expires_at: datetime | None = None
    devices_total: int | None = None
    devices_used: int | None = None
    traffic_bytes: int | None = None
    lte_traffic_bytes: int | None = None
    devices: list[KeyDevice] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    ok: bool = False
    error_code: str = "INTERNAL_ERROR"
    error_message: str = "Internal error"
    details: dict[str, Any] | None = None
