"""Admin Users schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AdminUserListItem(BaseModel):
    id: int
    tg_id: int
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    # NB: API field is `balance_kop` (admin frontend contract).
    # The DB column is `balance_kopecks`; renaming happens at the
    # serialization boundary (see api/admin/users.py).
    balance_kop: int
    active_subscriptions_count: int
    is_banned: bool
    ban_reason: str | None = None
    created_at: datetime


class AdminUsersPage(BaseModel):
    items: list[AdminUserListItem]
    total: int
    page: int
    page_size: int


class AdminUserDetail(BaseModel):
    id: int
    tg_id: int
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    language_code: str | None = None
    balance_kop: int
    is_banned: bool
    ban_reason: str | None = None
    created_at: datetime
    referrer: dict[str, Any] | None = None  # {id, tg_id, username}


class AdminUserPaymentItem(BaseModel):
    id: int
    subscription_id: int | None = None
    purpose: str
    provider: str
    amount_kop: int
    currency: str
    status: str
    created_at: datetime
    paid_at: datetime | None = None


class AdminUserSubscriptionItem(BaseModel):
    id: int
    tariff_id: int
    devices: int
    days: int
    status: str
    is_free_trial: bool
    started_at: datetime | None = None
    expires_at: datetime | None = None
    deactivated_at: datetime | None = None
    deactivation_reason: str | None = None
    key_url: str | None = None
    created_at: datetime


class AdminUserTicketItem(BaseModel):
    id: int
    code: str
    kind: str
    status: str
    closed_by: str | None = None
    created_at: datetime
    closed_at: datetime | None = None


class InvitedReferralItem(BaseModel):
    user: dict[str, Any]  # {id, tg_id, username, first_name, created_at}
    paid: bool
    bonus_paid_at: datetime | None = None


class AdminUserReferrals(BaseModel):
    referrer: dict[str, Any] | None = None
    invited: list[InvitedReferralItem]


class AdminUserBalanceTxItem(BaseModel):
    id: int
    amount_kop: int
    reason: str
    description: str | None = None
    balance_after_kop: int
    ref_payment_id: int | None = None
    ref_subscription_id: int | None = None
    created_at: datetime


class AdminUserBanRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class AdminUserBalanceAdjustRequest(BaseModel):
    amount_kop: int = Field(description="Signed delta in kopecks")
    reason: str = Field(min_length=1, max_length=2000)


class AdminUserBalanceAdjustResponse(BaseModel):
    user_id: int
    balance_kop: int
    delta_kop: int
