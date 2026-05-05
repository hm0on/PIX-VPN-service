"""User-related schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class UserUpsertRequest(BaseModel):
    tg_id: int
    username: str | None = Field(default=None, max_length=64)
    first_name: str | None = Field(default=None, max_length=128)
    last_name: str | None = Field(default=None, max_length=128)
    language_code: str | None = Field(default=None, max_length=8)
    ref_id: int | None = None
    start_payload: str | None = Field(default=None, max_length=128)


class UserResponse(ORMModel):
    id: int
    tg_id: int
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    language_code: str | None = None
    balance_kopecks: int
    is_banned: bool
    banned_reason: str | None = None
    ref_id: int | None = None
    created_at: datetime
    updated_at: datetime


class UserUpsertResponse(BaseModel):
    user: UserResponse
    created: bool
