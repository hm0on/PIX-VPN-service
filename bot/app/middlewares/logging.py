"""TraceMiddleware — generates a per-update trace_id and exposes it everywhere.

The trace_id is written both into ``data`` (so handlers can pick it up via DI)
and into ``trace_id_var`` ContextVar (so any nested ``structlog`` call and the
``BackendClient`` request layer attach the correct correlation id).
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, Update

from app.utils.logging import get_logger, trace_id_var, user_id_var

log = get_logger("bot.mw.trace")


def _extract_user_id(event: TelegramObject) -> int | None:
    if isinstance(event, Update):
        if event.message and event.message.from_user:
            return event.message.from_user.id
        if event.callback_query and event.callback_query.from_user:
            return event.callback_query.from_user.id
    if isinstance(event, (Message, CallbackQuery)) and event.from_user:
        return event.from_user.id
    return None


class TraceMiddleware(BaseMiddleware):
    """Add ``trace_id`` to ``data`` and to the ContextVar for the entire chain."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        trace_id = str(uuid.uuid4())
        data["trace_id"] = trace_id

        user_id = _extract_user_id(event)
        token_trace = trace_id_var.set(trace_id)
        token_user = user_id_var.set(user_id)

        started = time.monotonic()
        try:
            return await handler(event, data)
        finally:
            duration_ms = int((time.monotonic() - started) * 1000)
            log.debug(
                "update.processed",
                event_type=type(event).__name__,
                duration_ms=duration_ms,
            )
            trace_id_var.reset(token_trace)
            user_id_var.reset(token_user)
