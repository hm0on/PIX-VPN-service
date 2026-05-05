"""Stage 4 — support-group topic helper.

Centralises every interaction with the Telegram *forum group* used as the
support backbone:

- ensure a topic exists for a user (creating it lazily, then caching the
  ``message_thread_id`` in the backend);
- forward a user-side message into that topic together with the inline
  admin-actions keyboard (ban / close);
- emit small system notifications inside the topic (separator, closed,
  banned, …);
- notify the user in their private chat about ban/unban events.

All Telegram errors are caught locally and turned into either a one-time
retry (when the topic vanished) or a logged warning (when the user blocked
the bot). Callers therefore can safely ``await`` these helpers without
wrapping them in their own try/except — except for the bottom-line
forwarder, which re-raises after the retry budget is exhausted so the
caller can decide how to inform the user.
"""

from __future__ import annotations

from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import InlineKeyboardMarkup, Message
from aiogram.types import User as TgUser

from app.api_client import BackendClient
from app.config import Settings
from app.keyboards.ticket_admin import ticket_admin_actions_kb
from app.utils.logging import (
    LOG_LEVEL_CRITICAL,
    LOG_LEVEL_INFO,
    bot_log,
    get_logger,
)
from app.utils.texts import TextService

log = get_logger("bot.services.support_topic")

# Telegram error markers that mean "the topic is gone / unusable".
_TOPIC_GONE_MARKERS: tuple[str, ...] = (
    "TOPIC_CLOSED",
    "TOPIC_DELETED",
    "MESSAGE_THREAD_NOT_FOUND",
)


def _is_topic_gone(exc: TelegramBadRequest) -> bool:
    """Detect topic-vanished errors by message content."""
    msg = (exc.message or "").upper()
    return any(marker in msg for marker in _TOPIC_GONE_MARKERS)


def _resolve_user_fields(
    user: dict[str, Any] | TgUser,
) -> tuple[int, str, str | None]:
    """Return ``(backend_user_id, first_name, username)`` from any user shape.

    For an aiogram ``User`` we have only the Telegram-side identity; the
    backend id is unknown (caller passed the wrong shape) and we return 0
    so the caller can detect the problem. Real flows always pass the
    ``db_user`` dict.
    """
    if isinstance(user, dict):
        backend_user_id = int(user.get("id") or 0)
        first_name = (user.get("first_name") or "user") or "user"
        username = user.get("username")
        return backend_user_id, first_name, username
    return 0, user.first_name or "user", user.username


# --------------------------------------------------------------------------- #
# Topic provisioning                                                          #
# --------------------------------------------------------------------------- #


async def ensure_support_topic(
    bot: Bot,
    api: BackendClient,
    settings: Settings,
    user: dict[str, Any] | TgUser,
    ticket_code: str,
    *,
    texts: TextService,
) -> int:
    """Return ``message_thread_id`` for the given user, creating it if needed.

    ``user`` should be the backend ``db_user`` dict (preferred — it carries
    both the backend ``id`` and the cached ``first_name``). The backend
    cache is keyed by *backend* user id, NOT by ``tg_id``.
    """
    if settings.SUPPORT_GROUP_ID is None:
        raise RuntimeError("SUPPORT_GROUP_ID is not configured")

    backend_user_id, first_name, _username = _resolve_user_fields(user)
    if backend_user_id <= 0:
        raise RuntimeError("ensure_support_topic: backend user id is missing")

    cached = await api.get_support_topic(backend_user_id)
    cached_thread = cached.get("topic_thread_id") if isinstance(cached, dict) else None
    if cached_thread:
        return int(cached_thread)

    name = f"{ticket_code} · {first_name}"[:127]
    forum = await bot.create_forum_topic(
        chat_id=settings.SUPPORT_GROUP_ID,
        name=name,
    )
    new_thread_id = int(forum.message_thread_id)

    await api.save_support_topic(backend_user_id, new_thread_id, name)
    await bot_log(
        api,
        level=LOG_LEVEL_INFO,
        event="support_topic_created",
        user_id=backend_user_id,
        message=f"Created support topic for {ticket_code}",
        context={"thread_id": new_thread_id, "name": name},
    )
    return new_thread_id


# --------------------------------------------------------------------------- #
# Forwarding user messages → topic                                            #
# --------------------------------------------------------------------------- #


def _build_user_header(
    *,
    template: str,
    code: str,
    first_name: str | None,
    username: str | None,
    body: str,
) -> str:
    """Render the topic header from a texts-template, ignoring missing slots."""
    safe = {
        "code": code,
        "first_name": first_name or "—",
        "username": f"@{username}" if username else "—",
        "text": body or "",
    }
    try:
        return template.format(**safe)
    except (KeyError, IndexError, ValueError):
        # Fallback render — never let a template typo break message delivery.
        return (
            f"<b>Тикет:</b> {safe['code']}\n"
            f"<b>Пользователь:</b> {safe['first_name']}\n"
            f"<b>Юзернейм:</b> {safe['username']}\n\n"
            f"<b>Сообщение:</b>\n{safe['text']}"
        )


async def forward_user_message_to_topic(
    bot: Bot,
    api: BackendClient,
    settings: Settings,
    ticket: dict[str, Any],
    user: dict[str, Any] | TgUser,
    message: Message,
    texts: TextService,
    *,
    _retry: int = 0,
) -> None:
    """Forward a user message into the support topic with admin-action buttons.

    Recovers transparently when the cached topic was deleted/closed: creates
    a fresh one, updates the ticket→topic binding and retries once. After
    the retry the original error is re-raised — the caller decides whether
    to surface a "service unavailable" notice to the user.
    """
    if settings.SUPPORT_GROUP_ID is None:
        raise RuntimeError("SUPPORT_GROUP_ID is not configured")

    code = str(ticket.get("code") or "—")
    ticket_id = int(ticket.get("id") or 0)
    thread_id = int(ticket.get("topic_thread_id") or 0)

    _backend_user_id, first_name, username = _resolve_user_fields(user)

    # Choose template: ideas use a distinct header.
    template_key = (
        "support_topic_user_idea"
        if ticket.get("kind") == "idea"
        else "support_topic_user_message"
    )
    template = await texts.get(template_key)

    if message.text is not None:
        body_text: str = message.text
    elif message.caption is not None:
        body_text = message.caption
    else:
        body_text = ""

    header = _build_user_header(
        template=template,
        code=code,
        first_name=first_name,
        username=username,
        body=body_text,
    )

    kb: InlineKeyboardMarkup = ticket_admin_actions_kb(ticket_id)

    try:
        if message.photo:
            largest = message.photo[-1]
            await bot.send_photo(
                chat_id=settings.SUPPORT_GROUP_ID,
                message_thread_id=thread_id,
                photo=largest.file_id,
                caption=header,
                reply_markup=kb,
                parse_mode="HTML",
            )
        else:
            await bot.send_message(
                chat_id=settings.SUPPORT_GROUP_ID,
                message_thread_id=thread_id,
                text=header,
                reply_markup=kb,
                parse_mode="HTML",
            )
    except TelegramBadRequest as exc:
        if _is_topic_gone(exc) and _retry == 0:
            log.warning(
                "support_topic.gone_retrying",
                ticket_id=ticket_id,
                thread_id=thread_id,
                error=str(exc),
            )
            new_thread_id = await ensure_support_topic(
                bot, api, settings, user, code, texts=texts
            )
            try:
                await api.attach_topic_to_ticket(ticket_id, new_thread_id)
            except Exception as inner:
                log.warning(
                    "support_topic.attach_failed",
                    ticket_id=ticket_id,
                    thread_id=new_thread_id,
                    error=str(inner),
                )
            ticket = {**ticket, "topic_thread_id": new_thread_id}
            await forward_user_message_to_topic(
                bot, api, settings, ticket, user, message, texts, _retry=1
            )
            return
        await bot_log(
            api,
            level=LOG_LEVEL_CRITICAL,
            event="support_topic_forward_failed",
            user_id=ticket.get("user_id"),
            message=f"Failed to deliver user message to topic: {exc}",
            context={
                "ticket_id": ticket_id,
                "thread_id": thread_id,
                "retry": _retry,
            },
        )
        raise
    except TelegramForbiddenError as exc:
        # Bot kicked from the support group. Nothing we can do here.
        await bot_log(
            api,
            level=LOG_LEVEL_CRITICAL,
            event="support_topic_forbidden",
            user_id=ticket.get("user_id"),
            message=f"Bot forbidden in support group: {exc}",
            context={"ticket_id": ticket_id, "thread_id": thread_id},
        )
        raise


# --------------------------------------------------------------------------- #
# Topic-side notifications                                                    #
# --------------------------------------------------------------------------- #


async def _send_to_topic(
    bot: Bot,
    settings: Settings,
    thread_id: int,
    text: str,
) -> None:
    """Tiny wrapper around ``bot.send_message`` swallowing transient errors."""
    if settings.SUPPORT_GROUP_ID is None:
        return
    try:
        await bot.send_message(
            chat_id=settings.SUPPORT_GROUP_ID,
            message_thread_id=thread_id,
            text=text,
            parse_mode="HTML",
        )
    except (TelegramBadRequest, TelegramForbiddenError) as exc:
        log.warning(
            "support_topic.notification_failed",
            thread_id=thread_id,
            error=str(exc),
        )


async def notify_topic_separator(
    bot: Bot,
    settings: Settings,
    thread_id: int,
    code: str,
    *,
    texts: TextService,
) -> None:
    """Post a "new ticket" separator at the top of an existing topic."""
    text = await texts.get("support_topic_separator", code=code)
    await _send_to_topic(bot, settings, thread_id, text)


async def notify_topic_user_closed(
    bot: Bot,
    settings: Settings,
    thread_id: int,
    code: str,
    *,
    texts: TextService,
) -> None:
    """Notify the topic that the *user* closed their ticket."""
    text = await texts.get("support_topic_user_closed", code=code)
    await _send_to_topic(bot, settings, thread_id, text)


async def notify_topic_admin_closed(
    bot: Bot,
    settings: Settings,
    thread_id: int,
    code: str,
    *,
    texts: TextService,
) -> None:
    """Notify the topic that an *admin* closed the ticket."""
    text = await texts.get("support_topic_admin_closed", code=code)
    await _send_to_topic(bot, settings, thread_id, text)


async def notify_topic_user_banned(
    bot: Bot,
    settings: Settings,
    thread_id: int,
    username: str,
    reason: str,
    *,
    texts: TextService,
) -> None:
    """Confirm in-topic that the user behind it has been banned."""
    text = await texts.get(
        "support_topic_user_banned",
        username=username or "—",
        reason=reason or "—",
    )
    await _send_to_topic(bot, settings, thread_id, text)


async def notify_topic_user_unbanned(
    bot: Bot,
    settings: Settings,
    thread_id: int,
    username: str,
    *,
    texts: TextService,
) -> None:
    """Confirm in-topic that the user has been unbanned."""
    text = await texts.get(
        "support_topic_user_unbanned",
        username=username or "—",
    )
    await _send_to_topic(bot, settings, thread_id, text)


async def notify_topic_no_open_ticket(
    bot: Bot,
    settings: Settings,
    thread_id: int,
    *,
    texts: TextService,
) -> None:
    """Tell admins that the user has no open ticket — message NOT delivered."""
    text = await texts.get("support_topic_no_open_ticket")
    await _send_to_topic(bot, settings, thread_id, text)


# --------------------------------------------------------------------------- #
# User-side notifications (DM)                                                #
# --------------------------------------------------------------------------- #


async def notify_user_banned(
    bot: Bot,
    user_tg_id: int,
    reason: str,
    *,
    texts: TextService,
) -> None:
    """DM the user about the ban + reason. Swallow forbidden errors."""
    text = await texts.get("support_user_banned_notice", reason=reason or "—")
    try:
        await bot.send_message(user_tg_id, text, parse_mode="HTML")
    except TelegramForbiddenError as exc:
        log.warning(
            "support.notify_user_banned_blocked",
            tg_id=user_tg_id,
            error=str(exc),
        )
    except TelegramBadRequest as exc:
        log.warning(
            "support.notify_user_banned_failed",
            tg_id=user_tg_id,
            error=str(exc),
        )


async def notify_user_unbanned(
    bot: Bot,
    user_tg_id: int,
    *,
    texts: TextService,
) -> None:
    """DM the user about the unban. Swallow forbidden errors."""
    text = await texts.get("support_user_unbanned_notice")
    try:
        await bot.send_message(user_tg_id, text, parse_mode="HTML")
    except TelegramForbiddenError as exc:
        log.warning(
            "support.notify_user_unbanned_blocked",
            tg_id=user_tg_id,
            error=str(exc),
        )
    except TelegramBadRequest as exc:
        log.warning(
            "support.notify_user_unbanned_failed",
            tg_id=user_tg_id,
            error=str(exc),
        )


__all__ = [
    "ensure_support_topic",
    "forward_user_message_to_topic",
    "notify_topic_admin_closed",
    "notify_topic_no_open_ticket",
    "notify_topic_separator",
    "notify_topic_user_banned",
    "notify_topic_user_closed",
    "notify_topic_user_unbanned",
    "notify_user_banned",
    "notify_user_unbanned",
]
