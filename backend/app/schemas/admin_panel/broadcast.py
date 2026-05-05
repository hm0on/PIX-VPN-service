"""Admin Broadcasts schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class BroadcastButton(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=64)
    url: str = Field(min_length=1, max_length=2048)


class AdminBroadcast(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    html_text: str
    photo_file_id: str | None = None
    photo_path: str | None = None
    # URL the admin UI can use as <img src=...> for the previously uploaded
    # photo. Populated by the router from photo_path; not a DB column.
    photo_url: str | None = None
    buttons: list[BroadcastButton] | None = None
    buttons_per_row: int = 1
    target: str
    scheduled_at: datetime | None = None
    status: str
    recipients_total: int
    sent: int
    failed: int
    created_at: datetime
    created_by_admin_key_label: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class AdminBroadcastsPage(BaseModel):
    items: list[AdminBroadcast]
    total: int
    page: int
    page_size: int


class AdminBroadcastCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    html_text: str = Field(min_length=1, max_length=4096)
    target: Literal["all", "subscribers"] = "all"
    buttons: list[BroadcastButton] | None = None
    # 1..4: how many buttons go in one inline-keyboard row.
    buttons_per_row: int = Field(default=1, ge=1, le=4)
    scheduled_at: datetime | None = None

    @field_validator("buttons")
    @classmethod
    def _max_buttons(
        cls, v: list[BroadcastButton] | None
    ) -> list[BroadcastButton] | None:
        if v is not None and len(v) > 8:
            raise ValueError("max 8 buttons")
        return v


class AdminBroadcastPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    html_text: str | None = Field(default=None, min_length=1, max_length=4096)
    target: Literal["all", "subscribers"] | None = None
    buttons: list[BroadcastButton] | None = None
    buttons_per_row: int | None = Field(default=None, ge=1, le=4)
    scheduled_at: datetime | None = None

    @field_validator("buttons")
    @classmethod
    def _max_buttons(
        cls, v: list[BroadcastButton] | None
    ) -> list[BroadcastButton] | None:
        if v is not None and len(v) > 8:
            raise ValueError("max 8 buttons")
        return v


class AdminBroadcastSchedule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scheduled_at: datetime


class AdminBroadcastTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tg_id: int = Field(description="Recipient Telegram user id")


class AdminBroadcastTestResponse(BaseModel):
    ok: bool
    message_id: int | None = None
    error: str | None = None


class AdminBroadcastPhotoResponse(BaseModel):
    photo_path: str


class AdminBroadcastRecipient(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    broadcast_id: int
    user_id: int
    status: str
    error: str | None = None
    sent_at: datetime | None = None
    created_at: datetime


class AdminBroadcastRecipientsPage(BaseModel):
    items: list[AdminBroadcastRecipient]
    total: int
    page: int
    page_size: int
