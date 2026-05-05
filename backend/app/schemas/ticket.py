"""Stage 4 ticket / support-topic / ban schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.common import ORMModel

# --------- Ticket ---------

# The rest of the bot ↔ backend contract uses `tg_id`. The original Stage 4
# schemas used `tg_user_id`, which created an outlier the bot client never
# matched (the bot still sends `tg_id`). To stay backwards-compatible with
# existing tests AND the real bot client, the ticket-flow schemas accept
# both spellings — whichever the caller supplied is mapped to `tg_user_id`
# in the canonical field.


def _coerce_tg_aliases(values: object) -> object:
    """Allow `tg_id` as an alias for `tg_user_id` in incoming request bodies."""
    if isinstance(values, dict) and "tg_user_id" not in values and "tg_id" in values:
        values = {**values, "tg_user_id": values["tg_id"]}
    return values


class TicketOpenRequest(BaseModel):
    tg_user_id: int
    kind: Literal["support", "idea"]

    @model_validator(mode="before")
    @classmethod
    def _accept_tg_id(cls, values: object) -> object:
        return _coerce_tg_aliases(values)


class TicketResponse(ORMModel):
    id: int
    code: str
    user_id: int
    kind: str
    status: str
    topic_thread_id: int | None = None
    created_at: datetime


class TicketCloseRequest(BaseModel):
    by: Literal["user", "admin"]
    tg_user_id: int | None = None

    @model_validator(mode="before")
    @classmethod
    def _accept_tg_id(cls, values: object) -> object:
        return _coerce_tg_aliases(values)

    @model_validator(mode="after")
    def _require_tg_user_when_user_closes(self) -> TicketCloseRequest:
        if self.by == "user" and self.tg_user_id is None:
            raise ValueError("tg_user_id is required when by='user'")
        return self


class TicketMessageCreateRequest(BaseModel):
    direction: Literal["from_user", "from_admin"]
    message_type: Literal["text", "photo", "sticker"]
    text: str | None = None
    photo_file_id: str | None = Field(default=None, max_length=255)
    sticker_file_id: str | None = Field(default=None, max_length=255)
    tg_message_id: int | None = None


class TicketActiveResponse(BaseModel):
    ticket: TicketResponse | None = None


class TicketByThreadResponse(BaseModel):
    ticket: TicketResponse | None = None


class TopicAttachRequest(BaseModel):
    topic_thread_id: int


# --------- Ban ---------


class BanRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


# --------- Support Topic ---------


class SupportTopicSaveRequest(BaseModel):
    user_id: int
    topic_thread_id: int
    topic_name: str = Field(max_length=255)


class SupportTopicResponse(BaseModel):
    topic_thread_id: int | None = None
    topic_name: str | None = None
