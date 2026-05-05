"""Admin auth (Stage 5) extra schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class AdminKeyRotateRequest(BaseModel):
    """Body for POST /api/admin/auth/keys/rotate."""

    label: str = Field(min_length=1, max_length=64)
    grace_hours: int = Field(default=3, ge=0, le=168)


class AdminKeyRotateResponse(BaseModel):
    """Plaintext is returned ONCE here."""

    key: str
    label: str
    valid_until: datetime | None = None
    id: int


class AdminKeyListItem(ORMModel):
    id: int
    label: str
    created_at: datetime
    valid_until: datetime | None = None
    revoked_at: datetime | None = None
    is_current: bool = False
