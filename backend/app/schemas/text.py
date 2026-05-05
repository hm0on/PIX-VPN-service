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
    updated_at: datetime
    updated_by: str | None = None
