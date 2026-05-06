"""Admin Texts schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Allowed Telegram media kinds for admin-edited text attachments.
MediaKind = Literal["photo", "video", "animation"]
TextKind = Literal["message", "button"]


class AdminText(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    key: str
    value_html: str
    description: str | None = None
    media_file_id: str | None = None
    media_kind: MediaKind | None = None
    kind: TextKind = "message"
    icon_custom_emoji_id: str | None = None
    url: str | None = None
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

    For ``kind='button'`` rows the editor sends ``value_html`` as the plain
    label string (no HTML). The validator below rejects anything that looks
    like a tag — Telegram's ``InlineKeyboardButton.text`` doesn't accept HTML
    and silently truncates / mangles unexpected input, so a 422 here is
    friendlier than a runtime surprise. ``kind`` itself is not editable — the
    discriminator is set by the seeding migration and stays put.
    """

    model_config = ConfigDict(extra="forbid")

    value_html: str | None = Field(default=None, max_length=8000)
    description: str | None = None
    media_file_id: str | None = Field(default=None, max_length=256)
    media_kind: MediaKind | None = None
    icon_custom_emoji_id: str | None = Field(default=None, max_length=64)
    # Outbound URL for kind='button' rows. Pass an empty string or null to
    # clear (and turn the button back into a callback button). Validated
    # below: must start with http://, https://, or tg://.
    url: str | None = Field(default=None, max_length=512)

    @field_validator("media_file_id")
    @classmethod
    def _strip_file_id(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v or None

    @field_validator("icon_custom_emoji_id")
    @classmethod
    def _strip_emoji_id(cls, v: str | None) -> str | None:
        # Telegram custom-emoji ids are decimal digit strings (long-form
        # ``document_id``), but we don't enforce that here — Telegram does
        # at send-time and any error message from the API is preferable to
        # a false reject from us. Trim only.
        if v is None:
            return None
        v = v.strip()
        return v or None

    @field_validator("url")
    @classmethod
    def _validate_url(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        if not (
            v.startswith("http://")
            or v.startswith("https://")
            or v.startswith("tg://")
        ):
            raise ValueError(
                "URL must start with http://, https://, or tg://."
            )
        return v


def _looks_like_html(value: str) -> bool:
    """True if ``value`` contains an HTML tag-like sequence.

    Used by the button-mode validator. We don't try to be clever — any
    ``<...>`` triggers a reject. Editors sometimes send a literal ``<3``
    in the label, which would also trip this; the cure is "use entities"
    and the false-positive rate in our admin UI is acceptable.
    """
    import re

    return bool(re.search(r"<[A-Za-z/!?]", value))


class AdminButtonValidatedPatch(AdminTextPatch):
    """Patch wrapper that knows the row is a button — used by the API layer
    after fetching the existing row to gate validation by ``kind``.

    Pure-python helper, not exposed in the OpenAPI surface. Lives next to the
    schema so the validation rule is in one place.
    """

    @model_validator(mode="after")
    def _no_html_in_button_label(self) -> "AdminButtonValidatedPatch":
        if self.value_html is not None and _looks_like_html(self.value_html):
            raise ValueError(
                "Button label must be plain text — Telegram does not accept "
                "HTML in InlineKeyboardButton.text."
            )
        return self
