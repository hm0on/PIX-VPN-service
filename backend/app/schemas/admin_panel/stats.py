"""Stats schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class DashboardKPIs(BaseModel):
    total_users: int
    users_24h_delta: int
    active_subscriptions: int
    revenue_month: int
    revenue_today: int


class TimeseriesPoint(BaseModel):
    date: str  # YYYY-MM-DD
    amount: int = 0
    count: int = 0


class RevenueSeries(BaseModel):
    points: list[TimeseriesPoint]


class UsersSeries(BaseModel):
    points: list[TimeseriesPoint]


class RecentPaymentItem(BaseModel):
    id: int
    user_id: int
    user_tg_id: int | None = None
    user_username: str | None = None
    amount_kopecks: int
    provider: str
    created_at: datetime
    paid_at: datetime | None = None


class RecentUserItem(BaseModel):
    id: int
    tg_id: int
    username: str | None = None
    first_name: str | None = None
    created_at: datetime
