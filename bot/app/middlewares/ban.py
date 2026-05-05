"""BanMiddleware — silently drops updates from banned users.

By design (Stage 4 spec): a banned user's messages are *ignored* — the bot does
not reply at all. We still log the dropped update so it shows up in the admin
panel.

Bypass: events originating in the support group (``settings.SUPPORT_GROUP_ID``)
are NEVER dropped, even if the actor's user record happens to be flagged
``is_banned``. Without this bypass, an admin who once tested the bot as a
regular user and then got banned would silently lose the ability to act in
the support topics.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.config import Settings
from app.utils.logging import get_logger

log = get_logger("bot.mw.ban")


def _event_chat_id(event: TelegramObject) -> int | None:
    """Best-effort chat-id extraction for the events we care about."""
    if isinstance(event, Message):
        return event.chat.id
    if isinstance(event, CallbackQuery) and event.message is not None:
        return event.message.chat.id
    return None


class BanMiddleware(BaseMiddleware):
    """If ``data["db_user"].is_banned`` is true → drop the update.

    Exception: do not drop updates whose chat is the support group; those
    are admin-driven and must be processed regardless of the actor's ban
    flag.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        settings: Settings | None = data.get("settings")
        support_group_id = (
            settings.SUPPORT_GROUP_ID if settings is not None else None
        )
        if support_group_id is not None:
            chat_id = _event_chat_id(event)
            if chat_id == support_group_id:
                return await handler(event, data)

        db_user = data.get("db_user")
        if isinstance(db_user, dict) and db_user.get("is_banned"):
            log.info(
                "ban_mw.update_ignored",
                tg_id=db_user.get("tg_id"),
                user_id=db_user.get("id"),
                event_type=type(event).__name__,
            )
            return None  # silent drop.
        return await handler(event, data)
