"""Subscription schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.schemas.common import ORMModel


class SubscriptionResponse(ORMModel):
    id: int
    user_id: int
    tariff_id: int
    # ``tariff_name`` is denormalised here so the bot can render the tariff
    # label ("Basic", "Premium", "FREE", …) on subscription buttons and on
    # the subscription detail screen without making a second round-trip to
    # ``GET /tariffs``. Populated by the bot API endpoints (see
    # ``backend/app/api/bot/profile.py``); left ``None`` if the joined tariff
    # row was deleted (RESTRICT FK should normally prevent this).
    tariff_name: str | None = None
    tariff_duration_id: int | None = None
    provider_subscription_id: str | None = None
    key_url: str | None = None
    devices: int
    days: int
    status: str
    started_at: datetime | None = None
    expires_at: datetime | None = None
    deactivated_at: datetime | None = None
    deactivation_reason: str | None = None
    is_free_trial: bool
    created_at: datetime
    updated_at: datetime


class FreeTrialRequest(BaseModel):
    tg_id: int


class FreeTrialResponse(BaseModel):
    subscription: SubscriptionResponse
