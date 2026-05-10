"""Admin Subscriptions schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

# NorthLine spec enum. Mirrored from app.schemas.northline.NorthLineSubStatus
# but redeclared here so this module stays free of upstream client imports.
ProviderSubStatus = Literal["active", "suspended", "expired"]


class AdminSubListItem(BaseModel):
    id: int
    user_id: int
    user_tg_id: int | None = None
    user_username: str | None = None
    tariff_id: int
    # Denormalised so the admin table can render a tariff label without an
    # extra round-trip to /tariffs. ``tariff_code`` is the operator-facing
    # short identifier (``basic``, ``pro``…); ``tariff_name`` is the
    # display-name shown in the bot. Both are optional so we degrade to ``—``
    # when the tariff has been deleted (RESTRICT FK normally prevents this).
    tariff_code: str | None = None
    tariff_name: str | None = None
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
    tariff_code: str | None = None
    tariff_name: str | None = None
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
    """Proxy of NorthLine.get_key + raw.

    The reseller API doesn't currently return a per-device breakdown — only
    aggregate counts (``devices_used`` / ``devices_total``). We surface those
    aggregates separately so the admin UI can show "5 / 10 устройств" even
    when ``devices`` (the per-device list) is empty.
    """

    # NorthLine subscription status as the provider sees it. Diverging from
    # our local ``status`` is the whole reason :mod:`subscription_reconcile_service`
    # exists — surfacing it in the admin response lets ops eyeball drift
    # without waiting for the reconcile cron.
    provider_status: ProviderSubStatus | None = None
    traffic_bytes: int | None = None
    traffic_quota_gb: int | None = None
    # ``-1`` from NorthLine means «безлимит». Surface as a flag so the UI
    # doesn't have to interpret a magic value.
    unlimited_traffic: bool = False
    lte_traffic_bytes: int | None = None
    devices_total: int | None = None
    devices_used: int | None = None
    expires_at: datetime | None = None
    devices: list[dict[str, Any]] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class AdminSubBrandingRequest(BaseModel):
    """Per-subscription branding override (PUT /subscriptions/{id}/branding).

    All fields optional — admin can clear an override by sending ``null``.
    NorthLine accepts the same shape on its ``PATCH /keys/{id}/branding``.
    """

    custom_domain: str | None = Field(default=None, max_length=253)
    service_name: str | None = Field(default=None, max_length=128)
    service_description: str | None = Field(default=None, max_length=512)
    support_url: str | None = Field(default=None, max_length=512)


class AdminSubReconcileResponse(BaseModel):
    """Result of POST /subscriptions/{id}/reconcile.

    Mirrors the per-row outcome of ``subscription_reconcile_service`` so the
    admin UI can show ops what changed without re-fetching the row.
    """

    subscription_id: int
    action: Literal[
        "no_change",
        "status_flipped",
        "expires_extended",
        "expires_shrink_warned",
        "provider_unknown_key",
        "skipped_test",
        "api_error",
    ]
    old_status: str
    new_status: str
    old_expires_at: datetime | None = None
    new_expires_at: datetime | None = None
    provider_status: ProviderSubStatus | None = None
    message: str | None = None


class AdminSubDeactivateRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class AdminSubDeactivateResponse(BaseModel):
    id: int
    status: str
    deactivated_at: datetime | None = None
    deactivation_reason: str | None = None
    # NorthLine ``POST /keys/{id}/delete`` возвращает остаток списанных
    # средств — оставляем как информационное поле для админки.
    refund_rub: float | None = None


class AdminSubStopRequest(BaseModel):
    """Опциональная причина — сохраняется в ``deactivation_reason`` для
    единообразия с ``/deactivate`` (поле в БД одно)."""

    reason: str = Field(min_length=1, max_length=2000)


class AdminSubStopResponse(BaseModel):
    id: int
    status: str
    suspended_at: datetime | None = None
    reason: str | None = None


class AdminSubResumeResponse(BaseModel):
    id: int
    status: str
