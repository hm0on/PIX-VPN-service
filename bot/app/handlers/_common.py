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
from app.utils.texts import TextEntry, TextService, send_text_or_media

log = get_logger("bot.handlers.common")


async def safe_edit_or_send_media(
    target: Message | CallbackQuery,
    entry: TextEntry,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    """Render ``entry`` to ``target`` honouring its optional media attachment.

    This is the media-aware sibling of :func:`safe_edit_or_answer`. Use it
    whenever the operator might have attached a photo/video/animation to the
    text key in the admin panel — otherwise the file_id sits in the database
    doing nothing because plain ``edit_text`` ignores it.

    Behaviour:

    - ``Message`` target → :func:`send_text_or_media` (the usual reply path).
    - ``CallbackQuery`` target *with* media → ``edit_text`` cannot turn a
      text-only message into a media one (Telegram refuses), so we delete
      the source message and send a fresh one. This matches the pattern in
      ``handlers.start._show_main_menu``.
    - ``CallbackQuery`` target *without* media → keep the nicer in-place
      ``edit_text`` UX, falling back to ``answer`` on the inevitable
      ``TelegramBadRequest`` (e.g. when the source already has a caption).

    The callback itself is always ack'd so the spinner stops.
    """
    if isinstance(target, Message):
        await send_text_or_media(
            chat_id=target.chat.id,
            entry=entry,
            bot=target.bot,
            reply_markup=reply_markup,
        )
        return

    # CallbackQuery branch — always ack.
    try:
        await target.answer()
    except TelegramBadRequest:
        pass

    if target.message is None:
        return

    chat_id = target.message.chat.id
    bot = target.message.bot

    if entry.media_file_id:
        # Text→media or media→media transitions: delete the old message and
        # send a fresh one. ``edit_text`` cannot toggle the message kind.
        try:
            await target.message.delete()
        except TelegramBadRequest:
            pass
        await send_text_or_media(
            chat_id=chat_id,
            entry=entry,
            bot=bot,
            reply_markup=reply_markup,
        )
        return

    # Plain text — keep the in-place edit for snappy UX.
    try:
        await target.message.edit_text(
            entry.value_html, reply_markup=reply_markup
        )
    except TelegramBadRequest:
        await target.message.answer(
            entry.value_html, reply_markup=reply_markup
        )


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


