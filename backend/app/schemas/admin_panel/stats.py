"""Stats schemas.

Field names are aligned with the admin SPA contract:
  * KPI uses `users_total`, `users_delta_24h`, `active_subscriptions`,
    `revenue_month_kop`, `revenue_today_kop`.
  * Time-series endpoints return a flat array (no `points` wrapper).
  * Recent payments expose `amount_kop` (not `amount_kopecks`) and include
    `status` + `subscription_id` so the SPA can render badges and links.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class DashboardKPIs(BaseModel):
    users_total: int
    users_delta_24h: int
    active_subscriptions: int
    revenue_month_kop: int
    revenue_today_kop: int


class RevenuePoint(BaseModel):
    date: str  # YYYY-MM-DD
    amount_kop: int = 0


class UsersPoint(BaseModel):
    date: str  # YYYY-MM-DD
    count: int = 0


class RecentPaymentItem(BaseModel):
    id: int
    user_id: int
    user_tg_id: int | None = None
    user_username: str | None = None
    amount_kop: int
    provider: str
    status: str
    subscription_id: int | None = None
    created_at: datetime
    paid_at: datetime | None = None


class RecentUserItem(BaseModel):
    id: int
    tg_id: int
    username: str | None = None
    first_name: str | None = None
    created_at: datetime
