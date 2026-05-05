"""Admin Promo schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AdminPromo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    type: str
    value: int
    max_total_activations: int | None
    max_per_user: int
    current_activations: int
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    is_active: bool
    description: str | None = None
    created_at: datetime
    created_by_admin_key_label: str | None = None


class AdminPromoCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str | None = Field(default=None, min_length=1, max_length=64)
    type: Literal["balance", "discount_percent"]
    value: int = Field(ge=1)
    max_total_activations: int | None = Field(default=None, ge=1)
    max_per_user: int = Field(default=1, ge=1)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    is_active: bool = True
    description: str | None = None


class AdminPromoPatch(BaseModel):
    """Only the fields explicitly listed are mutable. The router rejects
    extras with 400."""

    model_config = ConfigDict(extra="forbid")

    is_active: bool | None = None
    max_total_activations: int | None = Field(default=None, ge=0)
    max_per_user: int | None = Field(default=None, ge=1)
    valid_until: datetime | None = None


class AdminPromoActivation(BaseModel):
    # Pure Pydantic — populated explicitly in the router because we join the
    # users table for tg_id/username and rename the amount field for the
    # admin-frontend contract.
    id: int
    promo_id: int
    user_id: int
    user_tg_id: int | None = None
    user_username: str | None = None
    payment_id: int | None = None
    applied_amount: int  # kopecks
    created_at: datetime


class AdminPromosPage(BaseModel):
    items: list[AdminPromo]
    total: int
    page: int
    page_size: int
