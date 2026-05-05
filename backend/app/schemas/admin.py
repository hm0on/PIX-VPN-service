"""Admin auth schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class AdminLoginRequest(BaseModel):
    key: str = Field(min_length=8, max_length=512)


class AdminTokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_at: datetime
    label: str
    kid: int


class AdminMeResponse(BaseModel):
    label: str
    kid: int
    issued_at: datetime
    expires_at: datetime


class AdminKeyResponse(ORMModel):
    id: int
    label: str
    created_at: datetime
    revoked_at: datetime | None = None
    valid_until: datetime | None = None


class AdminRotateRequest(BaseModel):
    new_label: str | None = Field(default=None, max_length=64)


class AdminRotateResponse(BaseModel):
    """One-time response — plaintext is returned only here."""

    new_plaintext_key: str
    new_key_id: int
    new_label: str
    previous_key_id: int | None
    previous_valid_until: datetime | None
    access_token: str
    expires_at: datetime
