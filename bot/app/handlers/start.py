"""/start handler + main menu navigation + subscription re-check callback."""

from __future__ import annotations

import re
from typing import Any

from aiogram import Bot, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message
from redis.asyncio import Redis

from app.api_client import BackendClient
from app.config import Settings
from app.handlers._common import safe_edit_or_send_media
from app.keyboards.main_menu import main_menu_kb
from app.middlewares.subscription_check import SUBSCRIBED_STATUSES, sub_cache_key
from app.utils.errors import BackendUnavailableError
from app.utils.logging import LOG_LEVEL_INFO, bot_log, get_logger
from app.utils.texts import TextService

# ``/start`` deep-link payloads we recognise. Backend ultimately decides
# whether ``ref_<n>`` is a valid referrer and whether to attribute it
# (e.g. only on a brand-new user). The bot only validates *shape* here.
_REF_PAYLOAD_RE = re.compile(r"^ref_\d{1,20}$")

router = Router(name="start")
log = get_logger("bot.handlers.start")


async def _show_main_menu(
    *,
    target: Message | CallbackQuery,
    texts: TextService,
) -> None:
    """Render the main menu.

    Uses :func:`safe_edit_or_send_media` so that if the operator has
    attached a ``media_file_id`` to the ``main_menu`` text via the admin
    panel, users see the cover image with the menu as a caption instead of
    plain text. The helper handles the text↔media transition (which
    ``edit_text`` cannot do on its own) by deleting the source message and
    sending a fresh one when media is involved.
    """
    entry = await texts.get_entry("main_menu")
    kb = await main_menu_kb(texts)
    await safe_edit_or_send_media(target, entry, reply_markup=kb)


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    texts: TextService,
    api: BackendClient,
    command: CommandObject,
    db_user: dict[str, Any] | None = None,
) -> None:
    """Greet the user and show the main menu.

    Stage 3: ``/start ref_<id>`` deep-links. ``UserMiddleware`` already
    upserted the user once (without payload), so we issue a second upsert
    here to forward the payload — backend decides whether to record the
    referral (typically only on freshly-created users). Failures are
    non-fatal: we log and still render the menu.
    """
    payload_raw = (command.args or "").strip()
    start_payload: str | None = None
    if payload_raw and _REF_PAYLOAD_RE.match(payload_raw):
        start_payload = payload_raw

    if start_payload is not None and message.from_user is not None:
        try:
            await api.upsert_user(message.from_user, start_payload=start_payload)
        except BackendUnavailableError as exc:
            log.warning(
                "start.ref_payload_upsert_failed",
                error=str(exc),
                tg_id=message.from_user.id,
            )
        except Exception as exc:  # noqa: BLE001 — non-fatal side-channel
            log.warning(
                "start.ref_payload_upsert_unexpected",
                error=str(exc),
                tg_id=message.from_user.id,
            )
        else:
            await bot_log(
                api,
                level=LOG_LEVEL_INFO,
                event="ref_payload_received",
                user_id=(db_user or {}).get("id"),
                message="Referral payload forwarded to backend",
                context={
                    "tg_id": message.from_user.id,
                    "start_payload": start_payload,
                },
            )

    await bot_log(
        api,
        level=0,
        event="user_start",
        user_id=(db_user or {}).get("id"),
        message="/start handled",
        context={
            "tg_id": getattr(message.from_user, "id", None),
            "start_payload": start_payload,
        },
    )
    await _show_main_menu(target=message, texts=texts)


@router.callback_query(lambda c: c.data == "main_menu")
async def cb_main_menu(callback: CallbackQuery, texts: TextService) -> None:
    """Re-render the main menu in place (edit-message flow)."""
    await _show_main_menu(target=callback, texts=texts)


@router.callback_query(lambda c: c.data == "check_sub")
async def cb_check_sub(
    callback: CallbackQuery,
    bot: Bot,
    redis: Redis,
    settings: Settings,
    texts: TextService,
    api: BackendClient,
    db_user: dict[str, Any] | None = None,
) -> None:
    """Force-refresh the subscription cache and re-check membership."""
    if callback.from_user is None:
        await callback.answer()
        return

    tg_id = int(callback.from_user.id)
    try:
        await redis.delete(sub_cache_key(tg_id))
    except Exception as exc:  # noqa: BLE001
        log.warning("check_sub.cache_invalidate_failed", error=str(exc))

    try:
        member = await bot.get_chat_member(
            chat_id=settings.REQUIRED_CHANNEL_ID,
            user_id=tg_id,
        )
    except Exception as exc:  # noqa: BLE001
        log.error("check_sub.get_chat_member_failed", error=str(exc))
        await callback.answer(
            "Не удалось проверить подписку. Попробуйте позже.",
            show_alert=True,
        )
        return

    if member.status in SUBSCRIBED_STATUSES:
        try:
            await redis.set(
                sub_cache_key(tg_id),
                "1",
                ex=settings.SUB_CHECK_TTL_SECONDS,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("check_sub.cache_write_failed", error=str(exc))

        await callback.answer("Спасибо, доступ открыт!", show_alert=False)
        await bot_log(
            api,
            level=0,
            event="subscription_confirmed",
            user_id=(db_user or {}).get("id"),
            message="User confirmed channel subscription",
            context={"tg_id": tg_id},
        )
        await _show_main_menu(target=callback, texts=texts)
        return

    await callback.answer("Подписка не найдена", show_alert=True)
