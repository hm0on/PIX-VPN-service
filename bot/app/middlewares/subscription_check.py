"""SubscriptionCheckMiddleware — gates the bot behind a Telegram-channel sub.

Behavior:
- For each Message/CallbackQuery, check whether the user is a member of
  ``REQUIRED_CHANNEL_ID`` via ``bot.get_chat_member``.
- Cache the result in Redis: ``sub_check:{tg_id} = "1"`` with TTL 5 minutes.
- If not subscribed → reply with ``channel_subscription_required`` text and
  inline keyboard (Subscribe URL + "I subscribed" callback). Stop processing.
- The ``check_sub`` callback is allowed to pass through so the handler can
  invalidate the cache and re-check.
- If the bot itself is not an admin of the channel and Telegram throws —
  log critical and let the update pass (we don't want a misconfigured channel
  to take the whole bot down).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware, Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, ChatMemberUpdated, Message, TelegramObject
from redis.asyncio import Redis

from app.config import Settings
from app.keyboards.common import subscription_check_kb
from app.utils.logging import LOG_LEVEL_CRITICAL, bot_log, get_logger
from app.utils.texts import TextService

log = get_logger("bot.mw.sub_check")

# Statuses that count as "subscribed". Public — reused by the ``check_sub``
# handler so the manual recheck applies identical semantics.
SUBSCRIBED_STATUSES = frozenset({"creator", "administrator", "member", "owner"})
# Backwards-compatible alias.
_SUBSCRIBED_STATUSES = SUBSCRIBED_STATUSES


def sub_cache_key(tg_id: int) -> str:
    """Redis key used by both the middleware and the ``check_sub`` handler."""
    return f"sub_check:{tg_id}"


# Backwards-compatible internal alias.
_cache_key = sub_cache_key


class SubscriptionCheckMiddleware(BaseMiddleware):
    """Force subscription before letting messages through."""

    def __init__(
        self,
        *,
        bot: Bot,
        redis: Redis,
        texts: TextService,
        settings: Settings,
    ) -> None:
        self._bot = bot
        self._redis = redis
        self._texts = texts
        self._channel_id = settings.REQUIRED_CHANNEL_ID
        self._channel_url = settings.REQUIRED_CHANNEL_URL
        self._ttl = settings.SUB_CHECK_TTL_SECONDS
        # Stage 4: events from the support group itself (admin replies in
        # topics) must NEVER trigger a subscription check — admins act there
        # in their staff role, not as bot users.
        self._support_group_id = settings.SUPPORT_GROUP_ID

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # Channel/membership update events are not user-driven — bypass check.
        if isinstance(event, ChatMemberUpdated):
            return await handler(event, data)

        # Stage 4: short-circuit anything happening in the support group.
        if self._support_group_id is not None:
            chat_id: int | None = None
            if isinstance(event, Message):
                chat_id = event.chat.id
            elif isinstance(event, CallbackQuery) and event.message is not None:
                chat_id = event.message.chat.id
            if chat_id == self._support_group_id:
                return await handler(event, data)

        # Resolve the originating user.
        if isinstance(event, Message):
            user = event.from_user
            source: Message | CallbackQuery | None = event
        elif isinstance(event, CallbackQuery):
            user = event.from_user
            source = event
            # Let the dedicated handler invalidate cache & re-check itself.
            if event.data == "check_sub":
                return await handler(event, data)
        else:
            return await handler(event, data)

        if user is None or source is None:
            return await handler(event, data)

        is_subscribed = await self._is_subscribed(user.id)
        if is_subscribed is None:
            # Bot misconfigured — let it pass to avoid a hard outage.
            return await handler(event, data)

        if is_subscribed:
            return await handler(event, data)

        await self._prompt_subscription(source)
        return None  # block downstream handlers.

    # ------------------------------------------------------------------ checks

    async def _is_subscribed(self, tg_id: int) -> bool | None:
        """``True``/``False``/``None`` (None = check failed, treat as bypass)."""
        cached = await self._redis.get(sub_cache_key(tg_id))
        if cached in (b"1", "1"):
            return True

        try:
            member = await self._bot.get_chat_member(self._channel_id, tg_id)
        except TelegramAPIError as exc:
            log.critical(
                "sub_check.api_error",
                tg_id=tg_id,
                channel_id=self._channel_id,
                error=str(exc),
            )
            await bot_log(
                api=None,  # don't risk awaiting backend from a hot path here
                level=LOG_LEVEL_CRITICAL,
                event="sub_check.api_error",
                user_id=tg_id,
                message="Cannot check channel membership — bot likely not an admin",
                context={"channel_id": self._channel_id, "error": str(exc)},
            )
            return None

        subscribed = member.status in _SUBSCRIBED_STATUSES
        if subscribed:
            await self._redis.set(sub_cache_key(tg_id), "1", ex=self._ttl)
        return subscribed

    # ----------------------------------------------------------------- prompts

    async def _prompt_subscription(self, source: Message | CallbackQuery) -> None:
        text = await self._texts.get("channel_subscription_required")
        kb = subscription_check_kb(self._channel_url)

        if isinstance(source, Message):
            await source.answer(text, parse_mode="HTML", reply_markup=kb)
            return

        # CallbackQuery
        await source.answer()
        if source.message is not None:
            try:
                await source.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
            except TelegramAPIError:
                # Could be "message is not modified" or message gone — fall back to send.
                await source.message.answer(text, parse_mode="HTML", reply_markup=kb)
