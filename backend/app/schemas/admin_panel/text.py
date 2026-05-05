"""Admin Texts schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Allowed Telegram media kinds for admin-edited text attachments.
MediaKind = Literal["photo", "video", "animation"]


class AdminText(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    key: str
    value_html: str
    description: str | None = None
    media_file_id: str | None = None
    media_kind: MediaKind | None = None
    updated_at: datetime
    updated_by: str | None = None


class AdminTextsPage(BaseModel):
    items: list[AdminText]
    total: int
    page: int
    page_size: int


class AdminTextPatch(BaseModel):
    """PATCH body — every field is optional but when ``media_file_id`` is sent
    we require ``media_kind`` (and vice versa) so the bot knows which Telegram
    method to call. Send both as ``null`` to clear the attachment.
    """

    model_config = ConfigDict(extra="forbid")

    value_html: str | None = Field(default=None, max_length=8000)
    description: str | None = None
    media_file_id: str | None = Field(default=None, max_length=256)
    media_kind: MediaKind | None = None

    @field_validator("media_file_id")
    @classmethod
    def _strip_file_id(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v or None
