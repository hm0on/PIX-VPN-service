"""Admin Subscriptions schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AdminSubListItem(BaseModel):
    id: int
    user_id: int
    user_tg_id: int | None = None
    user_username: str | None = None
    tariff_id: int
    devices: int
    days: int
    status: str
    is_free_trial: bool
    key_url: str | None = None
    expires_at: datetime | None = None
    created_at: datetime


class AdminSubsPage(BaseModel):
    items: list[AdminSubListItem]
    total: int
    page: int
    page_size: int


class AdminSubDetail(BaseModel):
    id: int
    user_id: int
    user_tg_id: int | None = None
    user_username: str | None = None
    tariff_id: int
    tariff_duration_id: int | None = None
    provider_subscription_id: str | None = None
    key_url: str | None = None
    devices: int
    days: int
    status: str
    is_free_trial: bool
    started_at: datetime | None = None
    expires_at: datetime | None = None
    deactivated_at: datetime | None = None
    deactivation_reason: str | None = None
    created_at: datetime


class AdminSubInfoResponse(BaseModel):
    """Proxy of NorthLine.get_key + raw."""

    traffic_bytes: int | None = None
    lte_traffic_bytes: int | None = None
    devices: list[dict[str, Any]] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class AdminSubDeactivateRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class AdminSubDeactivateResponse(BaseModel):
    id: int
    status: str
    deactivated_at: datetime | None = None
    deactivation_reason: str | None = None
