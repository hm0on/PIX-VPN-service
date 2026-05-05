"""Shared helpers for Stage-2+ handlers.

Centralises:
- ``safe_edit_or_answer``: replaces ``edit_text`` falling back to ``answer``
  on the inevitable ``TelegramBadRequest`` (e.g. when the source message is
  a photo+caption or already deleted).
- ``handle_backend_error``: maps :class:`BackendUnavailableError` and
  unexpected exceptions to a friendly text key so handlers don't have to
  repeat the boilerplate.
"""

from __future__ import annotations

from typing import Any

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from app.api_client import BackendClient
from app.utils.logging import (
    LOG_LEVEL_CRITICAL,
    LOG_LEVEL_WARNING,
    bot_log,
    get_logger,
)
from app.utils.texts import TextService

log = get_logger("bot.handlers.common")


async def safe_edit_or_answer(
    target: Message | CallbackQuery,
    text: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    """Edit the source message in-place or fall back to a fresh ``answer``.

    For ``CallbackQuery`` we always ack the callback (otherwise Telegram
    keeps the spinner running); errors on the ack itself are swallowed.
    """
    if isinstance(target, Message):
        await target.answer(text, reply_markup=reply_markup)
        return

    # CallbackQuery branch.
    try:
        await target.answer()
    except TelegramBadRequest:
        pass

    if target.message is None:
        return
    try:
        await target.message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest:
        await target.message.answer(text, reply_markup=reply_markup)


async def report_backend_unavailable(
    target: Message | CallbackQuery,
    *,
    api: BackendClient,
    texts: TextService,
    user_id: int | None,
    error: Exception,
    event: str,
) -> None:
    """Tell the user the backend is down + log a warning event."""
    text = await texts.get("service_unavailable")
    await safe_edit_or_answer(target, text)
    await bot_log(
        api,
        level=LOG_LEVEL_WARNING,
        event=event,
        user_id=user_id,
        message=str(error),
        context={"error": str(error), "type": type(error).__name__},
    )


async def report_unexpected(
    target: Message | CallbackQuery,
    *,
    api: BackendClient,
    texts: TextService,
    user_id: int | None,
    error: Exception,
    event: str,
    context: dict[str, Any] | None = None,
) -> None:
    """Tell the user something unexpected happened + log a critical event."""
    text = await texts.get("unexpected_error")
    try:
        await safe_edit_or_answer(target, text)
    except Exception as nested:  # noqa: BLE001 — we're already on the error path.
        log.warning("handler.error_reply_failed", error=str(nested))
    await bot_log(
        api,
        level=LOG_LEVEL_CRITICAL,
        event=event,
        user_id=user_id,
        message=f"{type(error).__name__}: {error}",
        context={**(context or {}), "type": type(error).__name__},
    )


