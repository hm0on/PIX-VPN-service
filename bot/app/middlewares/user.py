"""UserMiddleware — upserts the Telegram user via Backend API on each update.

The resulting user record is placed into ``data["db_user"]`` so downstream
middlewares (``BanMiddleware``, ``SubscriptionCheckMiddleware``) and handlers
can rely on it without re-querying.

If the Backend API is unavailable we DO NOT crash the update — we log the
failure and reply to the user with a friendly "service unavailable" message.
This keeps the bot polite during incidents.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, User

from app.api_client import BackendClient
from app.utils.errors import BackendUnavailableError
from app.utils.logging import LOG_LEVEL_WARNING, bot_log, get_logger
from app.utils.texts import TextService

log = get_logger("bot.mw.user")


# Stage 3: ``/start <payload>`` — we forward the raw payload to the backend
# only when it looks like a referral marker (``ref_<digits>``). The backend
# decides whether to honour it (new user vs returning, self-referral, etc.).
_START_PAYLOAD_RE = re.compile(r"^/start\s+(\S+)$")
_REF_PAYLOAD_RE = re.compile(r"^ref_\d+$")


def _extract_start_payload(event: TelegramObject) -> str | None:
    """Return the ``/start <payload>`` argument if it matches ``ref_<digits>``."""
    if not isinstance(event, Message):
        return None
    text = (event.text or "").strip()
    match = _START_PAYLOAD_RE.match(text)
    if match is None:
        return None
    payload = match.group(1)
    if _REF_PAYLOAD_RE.match(payload):
        return payload
    return None


def _extract_from_user(event: TelegramObject) -> tuple[User, Message | CallbackQuery] | None:
    """Return (User, originating event) for events we care about."""
    if isinstance(event, Message) and event.from_user is not None:
        return event.from_user, event
    if isinstance(event, CallbackQuery) and event.from_user is not None:
        return event.from_user, event
    return None


class UserMiddleware(BaseMiddleware):
    """Upsert the user; expose ``db_user`` and ``api`` to handlers."""

    def __init__(self, api: BackendClient, texts: TextService) -> None:
        self._api = api
        self._texts = texts

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # Always make api/texts available downstream.
        data.setdefault("api", self._api)
        data.setdefault("texts", self._texts)

        extracted = _extract_from_user(event)
        if extracted is None:
            # Channel posts, etc. — pass through with no upsert.
            return await handler(event, data)

        tg_user, source = extracted
        start_payload = _extract_start_payload(event)

        try:
            db_user = await self._api.upsert_user(
                tg_user, start_payload=start_payload
            )
        except BackendUnavailableError as exc:
            log.error("user_mw.backend_unavailable", error=str(exc), tg_id=tg_user.id)
            await bot_log(
                self._api,
                level=LOG_LEVEL_WARNING,
                event="backend_unavailable",
                user_id=tg_user.id,
                message="Backend unavailable on user upsert",
                context={"error": str(exc)},
            )
            await self._notify_unavailable(source)
            return None  # stop processing — but don't raise.

        data["db_user"] = db_user
        return await handler(event, data)

    async def _notify_unavailable(self, source: Message | CallbackQuery) -> None:
        """Best-effort friendly notice to the user."""
        text = await self._texts.get("service_unavailable")
        try:
            if isinstance(source, Message):
                await source.answer(text, parse_mode="HTML")
            else:  # CallbackQuery
                await source.answer("Сервис временно недоступен", show_alert=True)
                if source.message is not None:
                    await source.message.answer(text, parse_mode="HTML")
        except Exception as exc:  # noqa: BLE001 — we're already on the error path.
            log.warning("user_mw.notify_failed", error=str(exc))
