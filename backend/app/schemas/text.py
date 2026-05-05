"""Text schemas."""

from __future__ import annotations

from datetime import datetime

from app.schemas.common import ORMModel


class TextResponse(ORMModel):
    id: int
    key: str
    value_html: str
    description: str | None = None
    media_file_id: str | None = None
    media_kind: str | None = None
    # Stage 6: ``kind='button'`` rows carry the inline-keyboard button label
    # as ``value_html`` (plain text — no HTML), and may have an associated
    # ``icon_custom_emoji_id`` for the premium-emoji icon. Default 'message'
    # mirrors the DB-side server_default so older bot deployments that don't
    # know about ``kind`` see the same behaviour they used to.
    kind: str = "message"
    icon_custom_emoji_id: str | None = None
    updated_at: datetime
    updated_by: str | None = None
