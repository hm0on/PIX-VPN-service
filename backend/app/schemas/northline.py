"""Pydantic schemas for NorthLine reseller API requests and responses.

Mirrors https://northline-vpn.xyz/reseller-api-docs.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class KeyResponse(BaseModel):
    """Response of ``POST /keys``."""

    ok: bool = True
    subscription_id: str
    key: str
    expires_at: datetime
    devices: int
    days: int


class ExtendResponse(BaseModel):
    """Response of ``POST /keys/{id}/extend``.

    The provider returns ``new_expires_at`` and ``days_added`` (with optional
    ``charged_rub``). We expose the same fields under both old and new names
    so existing callers that read ``expires_at`` / ``added_days`` keep working.
    """

    model_config = ConfigDict(populate_by_name=True)

    ok: bool = True
    subscription_id: str
    expires_at: datetime = Field(validation_alias="new_expires_at")
    added_days: int = Field(validation_alias="days_added")
    charged_rub: int | None = None


class DeactivateResponse(BaseModel):
    """Synthetic — the reseller API has no deactivate endpoint, so this
    response is constructed locally inside :meth:`NorthLineClient.deactivate_key`
    to keep the admin flow uniform."""

    ok: bool = True
    subscription_id: str
    deactivated_at: datetime


class KeyDevice(BaseModel):
    """Per-device row. The reseller API does not currently return a device
    list, but the schema is kept in case it appears in a future revision —
    admin UI tolerates an empty list."""

    device_id: str
    name: str | None = None
    platform: str | None = None
    last_seen: datetime | None = None
    traffic_bytes: int | None = None


class KeyInfo(BaseModel):
    """Response of ``GET /keys/{id}``.

    The reseller API exposes:
    ``subscription_id, key, status, expires_at, devices (int — total slots),
    traffic_used_bytes, traffic_quota_gb``.

    For backward compatibility with the admin UI we keep the legacy aliases
    ``devices_total`` / ``traffic_bytes`` and a (currently always empty)
    ``device_list`` field. The reseller API does not return per-device
    breakdown in the current revision; ``device_list`` is left in for forward
    compat without colliding with the inbound ``devices`` integer field.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    ok: bool = True
    subscription_id: str
    key: str
    status: str
    expires_at: datetime | None = None
    devices_total: int | None = Field(default=None, validation_alias="devices")
    devices_used: int | None = None
    traffic_bytes: int | None = Field(
        default=None, validation_alias="traffic_used_bytes"
    )
    traffic_quota_gb: int | None = None
    lte_traffic_bytes: int | None = None
    device_list: list[KeyDevice] = Field(default_factory=list)

    # Back-compat shim: callers used to do ``info.devices`` (the list).
    @property
    def devices(self) -> list[KeyDevice]:
        return self.device_list


class ErrorResponse(BaseModel):
    ok: bool = False
    error_code: str = "INTERNAL_ERROR"
    error_message: str = "Internal error"
    details: dict[str, Any] | None = None
