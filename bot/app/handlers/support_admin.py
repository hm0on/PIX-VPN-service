"""Stage 4 — admin-side support handler.

Routes every event that originates inside the configured support group:

- text/photo/sticker messages in a topic → mirrored back to the user behind
  the ticket (after fetching the binding via ``api.get_ticket_by_thread``);
- inline-button callbacks under mirrored user messages
  (``tadm:ban|close|ban_cancel``);
- the FSM-driven "type the ban reason" message that follows
  :func:`cb_admin_ban`;
- in-topic slash commands ``/ban``, ``/unban``, ``/close``, ``/info``.

Only events from ``settings.SUPPORT_GROUP_ID`` are routed here; the
:func:`_in_support_group` filter short-circuits everything else so this
router is invisible to user-side flows.
"""

from __future__ import annotations

import contextlib
from typing import Any

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.api_client import BackendClient
from app.config import Settings
from app.keyboards.ticket_admin import (
    CB_BAN,
    CB_BAN_CANCEL,
    CB_CLOSE,
    ban_reason_cancel_kb,
)
from app.services import support_topic_helper
from app.states.ticket_admin import AdminTicketStates
from app.utils.errors import BackendClientError, BackendUnavailableError
from app.utils.logging import (
    LOG_LEVEL_INFO,
    LOG_LEVEL_WARNING,
    bot_log,
    get_logger,
)
from app.utils.texts import TextService

router = Router(name="support_admin")
log = get_logger("bot.handlers.support_admin")

# Cancel sentinel used by the ban-reason FSM step.
_CANCEL_TOKENS = frozenset({"/cancel", "отмена", "cancel"})


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _in_support_group(message_or_cb: Message | CallbackQuery, settings: Settings) -> bool:
    """True if the event originates from the configured support group chat."""
    if settings.SUPPORT_GROUP_ID is None:
        return False
    if isinstance(message_or_cb, Message):
        return message_or_cb.chat.id == settings.SUPPORT_GROUP_ID
    msg = message_or_cb.message
    return msg is not None and msg.chat.id == settings.SUPPORT_GROUP_ID


async def _resolve_ticket_user_tg_id(
    api: BackendClient, ticket: dict[str, Any]
) -> int | None:
    """Return the user's Telegram id from the ticket payload, or look it up."""
    tg_id = ticket.get("user_tg_id")
    if isinstance(tg_id, int) and tg_id > 0:
        return tg_id
    user_id = ticket.get("user_id")
    if not isinstance(user_id, int):
        return None
    user = await api.get_user_by_id(user_id)
    if isinstance(user, dict):
        candidate = user.get("tg_id")
        if isinstance(candidate, int) and candidate > 0:
            return candidate
    return None


async def _send_topic_reply(
    bot: Bot,
    settings: Settings,
    thread_id: int,
    text: str,
) -> None:
    """Send a small notice into the topic, swallowing transient errors."""
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
            "support_admin.topic_reply_failed",
            thread_id=thread_id,
            error=str(exc),
        )


async def _close_ticket_flow(
    bot: Bot,
    api: BackendClient,
    settings: Settings,
    texts: TextService,
    *,
    ticket: dict[str, Any],
    actor_tg_id: int | None,
) -> None:
    """Close a ticket from the admin side + notify both surfaces."""
    ticket_id = int(ticket.get("id") or 0)
    code = str(ticket.get("code") or "—")
    thread_id = int(ticket.get("topic_thread_id") or 0)

    # IMPORTANT: do NOT pass ``tg_user_id`` here. The backend's
    # ``/tickets/{id}/close`` interprets ``tg_user_id`` as the *ticket
    # owner* (used for the user-side close path to verify ownership) —
    # passing the admin's tg_id triggers an ownership-mismatch which is
    # masked as 404 ``ticket_not_found``. ``actor_tg_id`` is used only
    # for the local bot_log audit trail below.
    closed = await api.close_ticket(ticket_id, by="admin")
    final_code = str(closed.get("code") or code)

    user_tg_id = await _resolve_ticket_user_tg_id(api, ticket)
    if user_tg_id:
        try:
            user_text = await texts.get(
                "support_ticket_closed_by_admin", code=final_code
            )
            await bot.send_message(user_tg_id, user_text, parse_mode="HTML")
        except TelegramForbiddenError:
            log.warning(
                "support_admin.user_close_notice_blocked", tg_id=user_tg_id
            )
        except TelegramBadRequest as exc:
            log.warning(
                "support_admin.user_close_notice_failed",
                tg_id=user_tg_id,
                error=str(exc),
            )

    await support_topic_helper.notify_topic_admin_closed(
        bot, settings, thread_id, final_code, texts=texts
    )
    await bot_log(
        api,
        level=LOG_LEVEL_INFO,
        event="ticket_closed_by_admin",
        user_id=ticket.get("user_id"),
        message=f"Admin closed ticket {final_code}",
        context={
            "ticket_id": ticket_id,
            "thread_id": thread_id,
            "actor_tg_id": actor_tg_id,
        },
    )


async def _ban_user_flow(
    bot: Bot,
    api: BackendClient,
    settings: Settings,
    texts: TextService,
    *,
    target_tg_id: int,
    reason: str,
    ticket: dict[str, Any],
) -> None:
    """Run the bookkeeping after a successful ban: API, DM, topic notice."""
    thread_id = int(ticket.get("topic_thread_id") or 0)
    username = ticket.get("user_username") or ""

    await api.ban_user_by_tg(target_tg_id, reason)
    await support_topic_helper.notify_user_banned(
        bot, target_tg_id, reason, texts=texts
    )
    await support_topic_helper.notify_topic_user_banned(
        bot,
        settings,
        thread_id,
        username=str(username) if username else "—",
        reason=reason,
        texts=texts,
    )
    await bot_log(
        api,
        level=LOG_LEVEL_INFO,
        event="user_banned",
        user_id=ticket.get("user_id"),
        message=f"User banned: {reason}",
        context={
            "ticket_id": ticket.get("id"),
            "thread_id": thread_id,
            "tg_id": target_tg_id,
        },
    )


# --------------------------------------------------------------------------- #
# Slash commands in topics                                                    #
# --------------------------------------------------------------------------- #


@router.message(Command("close"))
async def cmd_close(
    message: Message,
    api: BackendClient,
    settings: Settings,
    texts: TextService,
    bot: Bot,
) -> None:
    """``/close`` — close the ticket bound to the current topic."""
    if not _in_support_group(message, settings):
        return
    if message.message_thread_id is None:
        return

    ticket = await api.get_ticket_by_thread(message.message_thread_id)
    if not ticket or ticket.get("status") != "open":
        await support_topic_helper.notify_topic_no_open_ticket(
            bot, settings, message.message_thread_id, texts=texts
        )
        return

    actor = message.from_user.id if message.from_user else None
    await _close_ticket_flow(
        bot, api, settings, texts, ticket=ticket, actor_tg_id=actor
    )


@router.message(Command("ban"))
async def cmd_ban(
    message: Message,
    command: CommandObject,
    api: BackendClient,
    settings: Settings,
    texts: TextService,
    bot: Bot,
) -> None:
    """``/ban <reason>`` — ban the ticket's author and close-flow notify."""
    if not _in_support_group(message, settings):
        return
    if message.message_thread_id is None:
        return

    raw_reason = (command.args or "").strip()
    if not raw_reason:
        await _send_topic_reply(
            bot,
            settings,
            message.message_thread_id,
            "Использование: /ban &lt;причина&gt;",
        )
        return

    ticket = await api.get_ticket_by_thread(message.message_thread_id)
    if not ticket:
        await support_topic_helper.notify_topic_no_open_ticket(
            bot, settings, message.message_thread_id, texts=texts
        )
        return

    target_tg_id = await _resolve_ticket_user_tg_id(api, ticket)
    if target_tg_id is None:
        await _send_topic_reply(
            bot,
            settings,
            message.message_thread_id,
            "Не удалось определить tg_id юзера.",
        )
        return

    await _ban_user_flow(
        bot,
        api,
        settings,
        texts,
        target_tg_id=target_tg_id,
        reason=raw_reason,
        ticket=ticket,
    )


@router.message(Command("unban"))
async def cmd_unban(
    message: Message,
    api: BackendClient,
    settings: Settings,
    texts: TextService,
    bot: Bot,
) -> None:
    """``/unban`` — clear the ban for the ticket's author."""
    if not _in_support_group(message, settings):
        return
    if message.message_thread_id is None:
        return

    ticket = await api.get_ticket_by_thread(message.message_thread_id)
    if not ticket:
        await support_topic_helper.notify_topic_no_open_ticket(
            bot, settings, message.message_thread_id, texts=texts
        )
        return

    target_tg_id = await _resolve_ticket_user_tg_id(api, ticket)
    if target_tg_id is None:
        await _send_topic_reply(
            bot,
            settings,
            message.message_thread_id,
            "Не удалось определить tg_id юзера.",
        )
        return

    await api.unban_user_by_tg(target_tg_id)
    await support_topic_helper.notify_user_unbanned(
        bot, target_tg_id, texts=texts
    )
    await support_topic_helper.notify_topic_user_unbanned(
        bot,
        settings,
        message.message_thread_id,
        username=str(ticket.get("user_username") or "—"),
        texts=texts,
    )
    await bot_log(
        api,
        level=LOG_LEVEL_INFO,
        event="user_unbanned",
        user_id=ticket.get("user_id"),
        message="User unbanned via /unban",
        context={"ticket_id": ticket.get("id"), "tg_id": target_tg_id},
    )


@router.message(Command("info"))
async def cmd_info(
    message: Message,
    api: BackendClient,
    settings: Settings,
    bot: Bot,
) -> None:
    """``/info`` — show a quick summary of the ticket's user inside the topic."""
    if not _in_support_group(message, settings):
        return
    if message.message_thread_id is None:
        return

    ticket = await api.get_ticket_by_thread(message.message_thread_id)
    if not ticket:
        await _send_topic_reply(
            bot,
            settings,
            message.message_thread_id,
            "Тикет в этом топике не найден.",
        )
        return

    target_tg_id = await _resolve_ticket_user_tg_id(api, ticket)
    if target_tg_id is None:
        await _send_topic_reply(
            bot,
            settings,
            message.message_thread_id,
            "Не удалось определить tg_id юзера.",
        )
        return

    balance_kop = 0
    try:
        balance_kop = await api.get_user_balance(target_tg_id)
    except BackendClientError as exc:
        log.warning("support_admin.balance_fetch_failed", error=str(exc))
    except BackendUnavailableError as exc:
        log.warning("support_admin.balance_unavailable", error=str(exc))

    subs_summary = "—"
    try:
        subs = await api.get_user_subscriptions(target_tg_id)
        active = [s for s in subs if s.get("status") == "active"]
        if active:
            subs_summary = ", ".join(
                f"{s.get('tariff_name', '?')} → {s.get('expires_at', '?')}"
                for s in active
            )
        else:
            subs_summary = "нет активных"
    except (BackendClientError, BackendUnavailableError) as exc:
        log.warning("support_admin.subs_fetch_failed", error=str(exc))

    rubles = balance_kop // 100
    body = (
        f"<b>Юзер:</b> @{ticket.get('user_username') or '—'}\n"
        f"<b>tg_id:</b> <code>{target_tg_id}</code>\n"
        f"<b>Баланс:</b> {rubles} ₽\n"
        f"<b>Подписки:</b> {subs_summary}"
    )
    await _send_topic_reply(bot, settings, message.message_thread_id, body)


# --------------------------------------------------------------------------- #
# FSM: ban-reason capture (must come BEFORE the generic message handler)      #
# --------------------------------------------------------------------------- #


@router.message(StateFilter(AdminTicketStates.awaiting_ban_reason))
async def msg_admin_ban_reason(
    message: Message,
    state: FSMContext,
    api: BackendClient,
    settings: Settings,
    texts: TextService,
    bot: Bot,
) -> None:
    """Free-text ban reason follow-up (or ``/cancel``)."""
    if not _in_support_group(message, settings):
        return

    raw = (message.text or "").strip()
    if not raw or raw.lower() in _CANCEL_TOKENS:
        await state.clear()
        if message.message_thread_id is not None:
            await _send_topic_reply(
                bot,
                settings,
                message.message_thread_id,
                "Бан отменён.",
            )
        return

    data = await state.get_data()
    target_tg_id = data.get("user_tg_id")
    ticket_id = data.get("ticket_id")
    thread_id = data.get("thread_id")
    username = data.get("user_username") or ""

    await state.clear()

    if not isinstance(target_tg_id, int) or not isinstance(ticket_id, int):
        await _send_topic_reply(
            bot,
            settings,
            message.message_thread_id or 0,
            "Контекст бана потерян — повторите попытку.",
        )
        return

    # Build a synthetic ticket dict for the helper — enough fields to drive
    # the in-topic notification + audit log.
    fake_ticket: dict[str, Any] = {
        "id": ticket_id,
        "topic_thread_id": thread_id,
        "user_username": username,
    }
    await _ban_user_flow(
        bot,
        api,
        settings,
        texts,
        target_tg_id=target_tg_id,
        reason=raw,
        ticket=fake_ticket,
    )


# --------------------------------------------------------------------------- #
# Generic admin → user message mirror                                         #
# --------------------------------------------------------------------------- #


@router.message(F.chat.type.in_({"group", "supergroup"}) & F.message_thread_id)
async def msg_admin_in_topic(
    message: Message,
    api: BackendClient,
    settings: Settings,
    texts: TextService,
    bot: Bot,
) -> None:
    """Mirror an admin's text/photo/sticker into the user's DM."""
    if not _in_support_group(message, settings):
        return

    # Ignore commands handled by dedicated routes above (Command filter would
    # match them first, but be defensive against double-routing).
    if message.text and message.text.startswith("/"):
        return

    # Bot's own messages can land here when posting to topics; skip.
    if message.from_user is not None and message.from_user.is_bot:
        return

    thread_id = message.message_thread_id
    if thread_id is None:
        return

    ticket = await api.get_ticket_by_thread(thread_id)
    if not ticket or ticket.get("status") != "open":
        await support_topic_helper.notify_topic_no_open_ticket(
            bot, settings, thread_id, texts=texts
        )
        return

    target_tg_id = await _resolve_ticket_user_tg_id(api, ticket)
    if target_tg_id is None:
        await _send_topic_reply(
            bot,
            settings,
            thread_id,
            "Не удалось определить tg_id юзера — сообщение не доставлено.",
        )
        return

    prefix_template = await texts.get("support_admin_reply_prefix")

    delivered_message_id: int | None = None
    message_type: str | None = None
    text_payload: str | None = None
    photo_file_id: str | None = None
    sticker_file_id: str | None = None

    try:
        if message.text:
            try:
                rendered = prefix_template.format(text=message.text)
            except (KeyError, IndexError, ValueError):
                rendered = f"{prefix_template}{message.text}"
            sent = await bot.send_message(
                target_tg_id, rendered, parse_mode="HTML"
            )
            delivered_message_id = sent.message_id
            message_type = "text"
            text_payload = message.text
        elif message.photo:
            largest = message.photo[-1]
            caption_src = message.caption or ""
            try:
                rendered_caption = prefix_template.format(text=caption_src)
            except (KeyError, IndexError, ValueError):
                rendered_caption = (
                    f"{prefix_template}{caption_src}" if caption_src else prefix_template
                )
            sent = await bot.send_photo(
                target_tg_id,
                photo=largest.file_id,
                caption=rendered_caption,
                parse_mode="HTML",
            )
            delivered_message_id = sent.message_id
            message_type = "photo"
            photo_file_id = largest.file_id
            text_payload = caption_src or None
        elif message.sticker:
            sent = await bot.send_sticker(
                target_tg_id, sticker=message.sticker.file_id
            )
            delivered_message_id = sent.message_id
            message_type = "sticker"
            sticker_file_id = message.sticker.file_id
        else:
            await _send_topic_reply(
                bot,
                settings,
                thread_id,
                "Этот тип сообщений не поддерживается.",
            )
            return
    except TelegramForbiddenError:
        await _send_topic_reply(
            bot,
            settings,
            thread_id,
            "Юзер заблокировал бота — сообщение не доставлено.",
        )
        await bot_log(
            api,
            level=LOG_LEVEL_WARNING,
            event="ticket_reply_blocked_by_user",
            user_id=ticket.get("user_id"),
            message="User has blocked the bot",
            context={"ticket_id": ticket.get("id"), "tg_id": target_tg_id},
        )
        return
    except TelegramBadRequest as exc:
        await _send_topic_reply(
            bot,
            settings,
            thread_id,
            f"Не удалось доставить сообщение: {exc.message}",
        )
        return

    if message_type is not None:
        try:
            await api.record_ticket_message(
                int(ticket["id"]),
                direction="from_admin",
                message_type=message_type,
                text=text_payload,
                photo_file_id=photo_file_id,
                sticker_file_id=sticker_file_id,
                tg_message_id=delivered_message_id,
            )
        except (BackendClientError, BackendUnavailableError) as exc:
            log.warning(
                "support_admin.record_message_failed",
                ticket_id=ticket.get("id"),
                error=str(exc),
            )


# --------------------------------------------------------------------------- #
# Inline-button callbacks                                                     #
# --------------------------------------------------------------------------- #


@router.callback_query(F.data.startswith(f"{CB_BAN}:"))
async def cb_admin_ban(
    callback: CallbackQuery,
    state: FSMContext,
    api: BackendClient,
    settings: Settings,
    texts: TextService,
    bot: Bot,
) -> None:
    """Start the ban-with-reason wizard and prompt the admin in-topic."""
    if not _in_support_group(callback, settings):
        await callback.answer()
        return
    if callback.data is None or callback.message is None:
        await callback.answer()
        return

    try:
        ticket_id = int(callback.data.rsplit(":", 1)[-1])
    except ValueError:
        await callback.answer()
        return

    thread_id = callback.message.message_thread_id

    # Resolve ticket to fetch the target tg_id + username.
    ticket: dict[str, Any] | None = None
    if thread_id is not None:
        ticket = await api.get_ticket_by_thread(thread_id)
    if ticket is None:
        await callback.answer("Тикет не найден или уже закрыт.", show_alert=True)
        return

    target_tg_id = await _resolve_ticket_user_tg_id(api, ticket)
    if target_tg_id is None:
        await callback.answer(
            "Не удалось определить tg_id юзера.", show_alert=True
        )
        return

    prompt_text = await texts.get("support_topic_ban_reason_prompt")
    sent: Message | None = None
    if settings.SUPPORT_GROUP_ID is not None and thread_id is not None:
        try:
            sent = await bot.send_message(
                chat_id=settings.SUPPORT_GROUP_ID,
                message_thread_id=thread_id,
                text=prompt_text,
                reply_markup=ban_reason_cancel_kb(),
                parse_mode="HTML",
            )
        except (TelegramBadRequest, TelegramForbiddenError) as exc:
            log.warning("support_admin.ban_prompt_failed", error=str(exc))

    await state.set_state(AdminTicketStates.awaiting_ban_reason)
    await state.update_data(
        ticket_id=ticket_id,
        user_tg_id=target_tg_id,
        user_id=ticket.get("user_id"),
        user_username=ticket.get("user_username") or "",
        thread_id=thread_id,
        prompt_message_id=sent.message_id if sent is not None else None,
    )
    await callback.answer()


@router.callback_query(F.data == CB_BAN_CANCEL)
async def cb_admin_ban_cancel(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
) -> None:
    """Cancel the ban-reason wizard, edit the prompt message inline."""
    if not _in_support_group(callback, settings):
        await callback.answer()
        return

    await state.clear()
    if callback.message is not None:
        with contextlib.suppress(TelegramBadRequest):
            await callback.message.edit_text("Отменено.")
    await callback.answer()


@router.callback_query(F.data.startswith(f"{CB_CLOSE}:"))
async def cb_admin_close(
    callback: CallbackQuery,
    api: BackendClient,
    settings: Settings,
    texts: TextService,
    bot: Bot,
) -> None:
    """Close the ticket from its inline button under the user message."""
    if not _in_support_group(callback, settings):
        await callback.answer()
        return
    if callback.data is None or callback.message is None:
        await callback.answer()
        return

    try:
        ticket_id = int(callback.data.rsplit(":", 1)[-1])
    except ValueError:
        await callback.answer()
        return

    thread_id = callback.message.message_thread_id

    # Prefer fetching by thread (fresher status); fall back to id.
    ticket: dict[str, Any] | None = None
    if thread_id is not None:
        ticket = await api.get_ticket_by_thread(thread_id)
    if ticket is None or int(ticket.get("id") or 0) != ticket_id:
        # Stale button (topic was reused for a new ticket) — close by id with
        # whatever metadata we have.
        ticket = ticket or {"id": ticket_id, "topic_thread_id": thread_id}

    actor = callback.from_user.id if callback.from_user else None
    try:
        await _close_ticket_flow(
            bot, api, settings, texts, ticket=ticket, actor_tg_id=actor
        )
    except (BackendClientError, BackendUnavailableError) as exc:
        await callback.answer(
            f"Не удалось закрыть: {exc}"[:200], show_alert=True
        )
        return

    # Drop the inline keyboard from the message we acted on.
    with contextlib.suppress(TelegramBadRequest):
        await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("Тикет закрыт.")
