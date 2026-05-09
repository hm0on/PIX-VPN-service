"""Admin Payments schemas — global listing."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class AdminPaymentListItem(BaseModel):
    id: int
    user_id: int
    user_tg_id: int | None = None
    user_username: str | None = None
    subscription_id: int | None = None
    purpose: str
    provider: str
    external_id: str | None = None
    amount_kop: int
    currency: str
    status: str
    created_at: datetime
    paid_at: datetime | None = None


class AdminPaymentsPage(BaseModel):
    items: list[AdminPaymentListItem]
    total: int
    page: int
    page_size: int
