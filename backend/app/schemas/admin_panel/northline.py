"""Admin → NorthLine reseller schemas.

Thin DTOs over :mod:`app.schemas.northline`. We don't reuse the upstream
classes directly because they carry a few back-compat aliases
(``KeyInfo.devices``, ``Field(validation_alias=...)``) that don't belong
in an admin-facing JSON contract — and because we want the freedom to
add admin-only fields (computed totals, per-row warnings) without
bleeding them into the provider client.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AdminResellerProfile(BaseModel):
    """GET /admin/northline/profile — relayed reseller balance/state."""

    provider_key: str
    label: str | None = None
    balance_rub: float
    active: bool = True
    issued_total: int = 0
    active_total: int = 0
    spent_rub: float = 0.0


class AdminPriceMatrixRow(BaseModel):
    days: int
    devices: int
    total_price_rub: float
    override_key: str | None = None


class AdminResellerPrices(BaseModel):
    """GET /admin/northline/prices."""

    provider_key: str
    price_matrix: list[AdminPriceMatrixRow] = Field(default_factory=list)


class AdminLtePackage(BaseModel):
    gb: int
    price_rub: float
    label: str | None = None
    rate: float | None = None


class AdminLtePackagesResponse(BaseModel):
    """GET /admin/northline/lte-packages."""

    packages: list[AdminLtePackage] = Field(default_factory=list)


class AdminPriceQuote(BaseModel):
    """GET /admin/northline/price-quote — proxied price calculator.

    The bot still uses static prices (per the product decision), but the
    admin UI calls this to estimate one-off custom orders or to verify
    that the upstream price matrix matches our tariff table.
    """

    model_config = ConfigDict(extra="ignore")

    days: int
    devices: int
    tariff_code: str | None = None
    total_price_rub: float
    regular_price_rub: float | None = None
    savings_rub: float | None = None
    discount_pct: int | None = None
    device_discount_pct: int | None = None
    term_discount_pct: int | None = None
    price_per_device_per_day: float | None = None
    traffic_quota_gb: int | None = None
    unlimited_traffic: bool = False
    lte_gb: int | None = None
    lte_addon_rub: float | None = None
    lte_rate_per_gb: float | None = None


class AdminBrandingResponse(BaseModel):
    """GET /admin/northline/branding — current reseller-wide branding."""

    branding: dict[str, Any] = Field(default_factory=dict)


class AdminBrandingUpdateRequest(BaseModel):
    """PUT /admin/northline/branding.

    Every field is optional so the admin can patch one key (say, just the
    support_url) without touching the rest. Sending ``null`` explicitly
    clears the value upstream.
    """

    custom_domain: str | None = Field(default=None, max_length=253)
    service_name: str | None = Field(default=None, max_length=128)
    service_description: str | None = Field(default=None, max_length=512)
    support_url: str | None = Field(default=None, max_length=512)


__all__ = [
    "AdminBrandingResponse",
    "AdminBrandingUpdateRequest",
    "AdminLtePackage",
    "AdminLtePackagesResponse",
    "AdminPriceMatrixRow",
    "AdminPriceQuote",
    "AdminResellerPrices",
    "AdminResellerProfile",
]
