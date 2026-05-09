"""Admin Promo schemas."""

from __future__ import annotations

from datetime import datetime, time, timezone
from typing import Literal

try:
    # 3.9+ stdlib; available in our Python 3.12 image.
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - fallback for very old runtimes
    ZoneInfo = None  # type: ignore[assignment]

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.config import get_settings


def _coerce_validity_window(value: datetime | None, *, end_of_day: bool) -> datetime | None:
    """Resolve admin-entered date / datetime values to an unambiguous instant.

    The admin UI uses ``<input type="date">`` for ``valid_from`` /
    ``valid_until``, which serializes as ``"YYYY-MM-DD"``. Pydantic happily
    parses that into a naive ``datetime`` at midnight, but a naive midnight
    is dangerously ambiguous: Postgres ``TIMESTAMPTZ`` will tag it with
    whatever the *session* TZ happens to be, and the validity check in
    ``promo_service`` later compares it against ``datetime.now(UTC)``.

    Concretely: an admin in Moscow who picks "valid until 2026-05-09" means
    "valid through the end of May 9th, Moscow time". Without this coercion
    we'd store ``2026-05-09 00:00`` UTC — almost a full day earlier than
    they meant, and on the wrong side of the perceived expiry. That's the
    "promo kept working past the date" bug users were reporting (the
    rollover happens during what they still consider that day).

    Rules:
    - ``None`` -> ``None``.
    - tz-aware datetime -> returned as-is.
    - naive datetime at exact midnight -> snap to start (00:00:00) or end
      (23:59:59.999999) of that calendar day in the configured app TZ
      (``settings.tz``, defaults to ``Europe/Moscow``), then convert to UTC.
    - any other naive datetime -> assume it's already in app TZ and
      convert to UTC.
    """
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc)

    settings = get_settings()
    tz = ZoneInfo(settings.tz) if ZoneInfo is not None else timezone.utc

    is_midnight = (
        value.hour == 0
        and value.minute == 0
        and value.second == 0
        and value.microsecond == 0
    )
    if is_midnight:
        boundary = (
            time(23, 59, 59, 999_999) if end_of_day else time(0, 0, 0)
        )
        local = datetime.combine(value.date(), boundary, tzinfo=tz)
    else:
        local = value.replace(tzinfo=tz)
    return local.astimezone(timezone.utc)


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

    @field_validator("valid_from", mode="after")
    @classmethod
    def _normalize_valid_from(cls, v: datetime | None) -> datetime | None:
        return _coerce_validity_window(v, end_of_day=False)

    @field_validator("valid_until", mode="after")
    @classmethod
    def _normalize_valid_until(cls, v: datetime | None) -> datetime | None:
        return _coerce_validity_window(v, end_of_day=True)


class AdminPromoPatch(BaseModel):
    """Only the fields explicitly listed are mutable. The router rejects
    extras with 400."""

    model_config = ConfigDict(extra="forbid")

    is_active: bool | None = None
    max_total_activations: int | None = Field(default=None, ge=0)
    max_per_user: int | None = Field(default=None, ge=1)
    valid_until: datetime | None = None

    @field_validator("valid_until", mode="after")
    @classmethod
    def _normalize_valid_until(cls, v: datetime | None) -> datetime | None:
        return _coerce_validity_window(v, end_of_day=True)


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


# Re-export for tests that want to verify the coercion directly.
__all__ = [
    "AdminPromo",
    "AdminPromoCreate",
    "AdminPromoPatch",
    "AdminPromoActivation",
    "AdminPromosPage",
    "_coerce_validity_window",
]
