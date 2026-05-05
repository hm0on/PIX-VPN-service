"""Stage 4 — user-side support / idea ticket router.

Owns every interaction the *user* has with the ticket flow:

- ``support`` / ``idea`` callbacks → show the active-ticket card or the
  "create ticket" prompt;
- ``ticket:create:{kind}`` → open a ticket via backend, mount the persistent
  reply keyboard, and ask the admin-side helper to ensure a forum topic
  exists (the actual mirroring happens in :func:`msg_in_ticket`);
- messages received while the user is in :class:`TicketStates.in_ticket`
  → record + mirror to the topic (text/photo only; sticker/document/video/
  audio/voice/animation are rejected with a friendly notice);
- ``Закрыть тикет`` reply-button → confirm prompt → close ticket;
- catch-all for plain messages outside any ticket state → polite nudge.

The admin-side support flow lives in a parallel module (it observes the
support-group topic and DMs the user back). This file MUST NOT import or
edit anything in that module — they cooperate via the
:mod:`app.services.support_topic_helper` skeleton.
"""

from __future__ import annotations

from typing import Any

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from redis.asyncio import Redis

from app.api_client import BackendClient
from app.config import Settings
from app.handlers._common import (
    report_backend_unavailable,
    report_unexpected,
    safe_edit_or_answer,
)
from app.keyboards.ticket import (
    CB_TICKET_CLOSE_NO,
    CB_TICKET_CLOSE_YES,
    CB_TICKET_CREATE_IDEA,
    CB_TICKET_CREATE_SUPPORT,
    CLOSE_TICKET_BUTTON_TEXT,
    idea_no_ticket_kb,
    remove_kb,
    support_no_ticket_kb,
    ticket_active_reply_kb,
    ticket_close_confirm_kb,
)
from app.services import support_topic_helper
from app.states.ticket import TicketStates
from app.utils.errors import (
    BackendClientError,
    BackendConflictError,
    BackendUnavailableError,
)
from app.utils.logging import LOG_LEVEL_INFO, LOG_LEVEL_WARNING, bot_log, get_logger
from app.utils.texts import TextService

router = Router(name="support")
log = get_logger("bot.handlers.support")


# Anti-flood: at most this many user messages per minute inside an open
# ticket — beyond it we silently drop additional messages and reply with the
# rate-limit text. Tunables matched to stage4.md §7.
_FLOOD_LIMIT = 30
_FLOOD_WINDOW_SECONDS = 60


def _flood_key(tg_id: int) -> str:
    return f"support_flood:{tg_id}"


async def _is_flooded(redis: Redis, tg_id: int) -> bool:
    """Increment the per-user counter and return True if the limit is exceeded."""
    try:
        count = await redis.incr(_flood_key(tg_id))
    except Exception as exc:  # noqa: BLE001 — anti-flood failure must not crash the flow
        log.warning("support.flood_incr_failed", error=str(exc), tg_id=tg_id)
        return False
    if count == 1:
        try:
            await redis.expire(_flood_key(tg_id), _FLOOD_WINDOW_SECONDS)
        except Exception as exc:  # noqa: BLE001
            log.warning("support.flood_expire_failed", error=str(exc), tg_id=tg_id)
    return count > _FLOOD_LIMIT


async def _enter_active_ticket(
    *,
    callback: CallbackQuery,
    texts: TextService,
    state: FSMContext,
    ticket: dict[str, Any],
    text_key: str,
) -> None:
    """Render the "ticket open" inline card and mount the reply keyboard.

    Inline messages can't carry reply keyboards, so we send a tiny plain
    helper message immediately after the inline card to attach the
    persistent ``Закрыть тикет`` button. FSM is updated in place.
    """
    code = str(ticket.get("code") or "")
    kind = str(ticket.get("kind") or "support")
    text = await texts.get(text_key, code=code)
    await safe_edit_or_answer(callback, text)

    await state.set_state(TicketStates.in_ticket)
    await state.update_data(
        ticket_id=ticket.get("id"),
        ticket_code=code,
        ticket_kind=kind,
    )

    if callback.message is not None:
        # The reply-keyboard payload needs a real message — Telegram won't
        # mount it on a callback ack. A single dot is the minimum that
        # passes Telegram's "non-empty text" validation.
        try:
            await callback.message.answer("…", reply_markup=ticket_active_reply_kb())
        except TelegramBadRequest as exc:
            log.warning("support.reply_kb_mount_failed", error=str(exc))


# ------------------------------- entry points -------------------------------


@router.callback_query(F.data == "support")
async def cb_support(
    callback: CallbackQuery,
    api: BackendClient,
    texts: TextService,
    state: FSMContext,
    db_user: dict[str, Any] | None = None,
) -> None:
    """Open the support section — either the active-ticket card or the prompt."""
    if callback.from_user is None:
        await callback.answer()
        return
    tg_id = callback.from_user.id
    user_id = (db_user or {}).get("id")

    try:
        ticket = await api.get_active_ticket(tg_id)
    except BackendUnavailableError as exc:
        await report_backend_unavailable(
            callback, api=api, texts=texts, user_id=user_id,
            error=exc, event="support_active_ticket_backend_unavailable",
        )
        return
    except Exception as exc:  # noqa: BLE001
        await report_unexpected(
            callback, api=api, texts=texts, user_id=user_id,
            error=exc, event="support_active_ticket_unexpected",
        )
        return

    if ticket is None:
        text = await texts.get("support_no_active_ticket")
        await safe_edit_or_answer(
            callback, text, reply_markup=await support_no_ticket_kb(texts)
        )
        return

    await _enter_active_ticket(
        callback=callback,
        texts=texts,
        state=state,
        ticket=ticket,
        text_key="support_active_ticket",
    )


@router.callback_query(F.data == "idea")
async def cb_idea(
    callback: CallbackQuery,
    api: BackendClient,
    texts: TextService,
    state: FSMContext,
    db_user: dict[str, Any] | None = None,
) -> None:
    """Open the idea section — mirrors :func:`cb_support` with idea-specific copy."""
    if callback.from_user is None:
        await callback.answer()
        return
    tg_id = callback.from_user.id
    user_id = (db_user or {}).get("id")

    try:
        ticket = await api.get_active_ticket(tg_id)
    except BackendUnavailableError as exc:
        await report_backend_unavailable(
            callback, api=api, texts=texts, user_id=user_id,
            error=exc, event="idea_active_ticket_backend_unavailable",
        )
        return
    except Exception as exc:  # noqa: BLE001
        await report_unexpected(
            callback, api=api, texts=texts, user_id=user_id,
            error=exc, event="idea_active_ticket_unexpected",
        )
        return

    if ticket is None:
        text = await texts.get("idea_no_active_ticket")
        await safe_edit_or_answer(
            callback, text, reply_markup=await idea_no_ticket_kb(texts)
        )
        return

    # If the user already has any open ticket (kind doesn't matter — backend
    # enforces "1 open per user"), show the active card with the matching copy.
    text_key = (
        "idea_active_ticket"
        if str(ticket.get("kind")) == "idea"
        else "support_active_ticket"
    )
    await _enter_active_ticket(
        callback=callback,
        texts=texts,
        state=state,
        ticket=ticket,
        text_key=text_key,
    )


# ------------------------------ ticket creation -----------------------------


@router.callback_query(F.data.in_({CB_TICKET_CREATE_SUPPORT, CB_TICKET_CREATE_IDEA}))
async def cb_ticket_create(
    callback: CallbackQuery,
    api: BackendClient,
    texts: TextService,
    state: FSMContext,
    bot: Bot,
    settings: Settings,
    db_user: dict[str, Any] | None = None,
) -> None:
    """Create a ticket of the requested kind, then enter the in-ticket state."""
    if callback.from_user is None or callback.data is None:
        await callback.answer()
        return

    kind = "support" if callback.data == CB_TICKET_CREATE_SUPPORT else "idea"
    tg_id = callback.from_user.id
    user_id = (db_user or {}).get("id")

    try:
        ticket = await api.open_ticket(tg_id, kind)
    except BackendConflictError as exc:
        existing_code = ""
        if isinstance(exc.payload, dict):
            existing_code = str(exc.payload.get("code") or exc.payload.get("ticket_code") or "")
        text = await texts.get("support_already_open", code=existing_code or "—")
        await safe_edit_or_answer(callback, text)
        await bot_log(
            api,
            level=LOG_LEVEL_INFO,
            event="ticket_open_conflict",
            user_id=user_id,
            message="User attempted to open a second ticket",
            context={"kind": kind, "tg_id": tg_id},
        )
        return
    except BackendClientError as exc:
        await report_unexpected(
            callback, api=api, texts=texts, user_id=user_id,
            error=exc, event="ticket_open_client_error",
            context={"kind": kind, "error_code": exc.error_code},
        )
        return
    except BackendUnavailableError as exc:
        await report_backend_unavailable(
            callback, api=api, texts=texts, user_id=user_id,
            error=exc, event="ticket_open_backend_unavailable",
        )
        return
    except Exception as exc:  # noqa: BLE001
        await report_unexpected(
            callback, api=api, texts=texts, user_id=user_id,
            error=exc, event="ticket_open_unexpected",
            context={"kind": kind},
        )
        return

    code = str(ticket.get("code") or "")
    text_key = "support_ticket_created" if kind == "support" else "idea_ticket_created"

    text = await texts.get(text_key, code=code)
    await safe_edit_or_answer(callback, text)

    await state.set_state(TicketStates.in_ticket)
    await state.update_data(
        ticket_id=ticket.get("id"),
        ticket_code=code,
        ticket_kind=kind,
    )

    if callback.message is not None:
        try:
            await callback.message.answer("…", reply_markup=ticket_active_reply_kb())
        except TelegramBadRequest as exc:
            log.warning("support.create_reply_kb_mount_failed", error=str(exc))

    # Stage 4 spec §2 calls for creating the topic eagerly (so the admin
    # doesn't see a "phantom" ticket without a topic). Pass ``db_user`` when
    # available — the helper prefers it over the raw aiogram User because it
    # carries the backend user-id used to key the support-topic cache.
    helper_user: dict[str, Any] | Any = (
        db_user if isinstance(db_user, dict) else callback.from_user
    )
    try:
        thread_id = await support_topic_helper.ensure_support_topic(
            bot, api, settings, helper_user, code, texts=texts,
        )
        if isinstance(thread_id, int) and isinstance(ticket.get("id"), int):
            try:
                await api.attach_topic_to_ticket(int(ticket["id"]), thread_id)
            except Exception as inner_exc:  # noqa: BLE001 — best-effort.
                log.warning(
                    "support.attach_topic_failed",
                    error=str(inner_exc),
                )
            # If the user already had a topic from a previous ticket, drop a
            # separator so the admin sees that this is a fresh conversation.
            try:
                await support_topic_helper.notify_topic_separator(
                    bot, settings, thread_id, code, texts=texts,
                )
            except Exception as inner_exc:  # noqa: BLE001 — best-effort.
                log.warning(
                    "support.notify_topic_separator_failed",
                    error=str(inner_exc),
                )
    except Exception as exc:  # noqa: BLE001 — topic creation is best-effort.
        log.warning("support.ensure_topic_failed", error=str(exc))

    await bot_log(
        api,
        level=LOG_LEVEL_INFO,
        event="ticket_opened",
        user_id=user_id,
        message="User opened a ticket",
        context={"kind": kind, "tg_id": tg_id, "code": code},
    )


# ----------------------------- close confirmation ---------------------------


@router.message(
    StateFilter(TicketStates.in_ticket),
    F.text == CLOSE_TICKET_BUTTON_TEXT,
)
async def msg_close_button(
    message: Message,
    texts: TextService,
    state: FSMContext,
) -> None:
    """User tapped the persistent "Закрыть тикет" button → ask to confirm."""
    text = await texts.get("support_active_ticket")
    # The active-ticket text expects a ``code`` placeholder; reuse the FSM data.
    data = await state.get_data()
    code = str(data.get("ticket_code") or "—")
    prompt = (await texts.get("support_active_ticket", code=code))
    # Keep the prompt minimal — the inline confirm carries the action.
    await message.answer(
        f"{prompt}\n\nЗакрыть тикет?",
        reply_markup=await ticket_close_confirm_kb(texts),
    )
    await state.set_state(TicketStates.awaiting_close_confirm)
    # Silence unused-var hint — we render via ``prompt`` above.
    _ = text


@router.callback_query(
    F.data == CB_TICKET_CLOSE_NO,
    StateFilter(TicketStates.awaiting_close_confirm),
)
async def cb_ticket_close_no(
    callback: CallbackQuery,
    texts: TextService,
    state: FSMContext,
) -> None:
    """User cancelled close — drop back into the in-ticket state."""
    text = await texts.get("support_close_cancelled")
    await safe_edit_or_answer(callback, text)
    await state.set_state(TicketStates.in_ticket)


@router.callback_query(
    F.data == CB_TICKET_CLOSE_YES,
    StateFilter(TicketStates.awaiting_close_confirm),
)
async def cb_ticket_close_yes(
    callback: CallbackQuery,
    api: BackendClient,
    texts: TextService,
    state: FSMContext,
    bot: Bot,
    settings: Settings,
    db_user: dict[str, Any] | None = None,
) -> None:
    """User confirmed — close the ticket via backend and clean up the UI."""
    if callback.from_user is None:
        await callback.answer()
        return

    user_id = (db_user or {}).get("id")
    data = await state.get_data()
    ticket_id = data.get("ticket_id")
    code = str(data.get("ticket_code") or "—")

    if not isinstance(ticket_id, int):
        # Stale state — clear and bail with a friendly note.
        await state.clear()
        await safe_edit_or_answer(callback, await texts.get("support_close_cancelled"))
        return

    try:
        await api.close_ticket(ticket_id, by="user", tg_user_id=callback.from_user.id)
    except BackendUnavailableError as exc:
        await report_backend_unavailable(
            callback, api=api, texts=texts, user_id=user_id,
            error=exc, event="ticket_close_backend_unavailable",
        )
        return
    except Exception as exc:  # noqa: BLE001
        await report_unexpected(
            callback, api=api, texts=texts, user_id=user_id,
            error=exc, event="ticket_close_unexpected",
            context={"ticket_id": ticket_id},
        )
        return

    text = await texts.get("support_ticket_closed_by_user", code=code)
    await safe_edit_or_answer(callback, text)

    if callback.message is not None:
        # Send a tiny follow-up message purely to drop the persistent reply KB.
        try:
            await callback.message.answer("…", reply_markup=remove_kb())
        except TelegramBadRequest as exc:
            log.warning("support.remove_kb_failed", error=str(exc))

    # Notify the support topic if we know its thread_id. Stage 4 stores the
    # binding on the ticket itself; if the helper returned None on creation
    # we silently skip — the admin will still see the close in the next
    # admin action against the (now closed) ticket.
    thread_id_raw = data.get("topic_thread_id")
    if not isinstance(thread_id_raw, int):
        # Fallback: pull the user→topic cache straight from backend.
        backend_user_id = (db_user or {}).get("id")
        if isinstance(backend_user_id, int):
            try:
                topic_meta = await api.get_support_topic(backend_user_id)
                tt = topic_meta.get("topic_thread_id") if isinstance(topic_meta, dict) else None
                if isinstance(tt, int):
                    thread_id_raw = tt
            except Exception as exc:  # noqa: BLE001 — best-effort lookup.
                log.warning("support.lookup_topic_for_close_failed", error=str(exc))
    if isinstance(thread_id_raw, int):
        try:
            await support_topic_helper.notify_topic_user_closed(
                bot, settings, thread_id_raw, code, texts=texts,
            )
        except Exception as exc:  # noqa: BLE001 — topic notification is best-effort.
            log.warning("support.notify_topic_user_closed_failed", error=str(exc))

    await state.clear()

    await bot_log(
        api,
        level=LOG_LEVEL_INFO,
        event="ticket_closed_by_user",
        user_id=user_id,
        message="User closed their ticket",
        context={"ticket_id": ticket_id, "code": code},
    )


# ---------------------------- in-ticket messages ----------------------------


@router.message(StateFilter(TicketStates.in_ticket))
async def msg_in_ticket(
    message: Message,
    api: BackendClient,
    texts: TextService,
    state: FSMContext,
    bot: Bot,
    settings: Settings,
    redis: Redis,
    db_user: dict[str, Any] | None = None,
) -> None:
    """Every non-command, non-close-button message while a ticket is open.

    Order of checks (cheap → expensive):
    1. Skip slash-commands (they should be handled by their own routers).
    2. Anti-flood (Redis INCR with 60s TTL).
    3. Resolve the active ticket from the backend (defensive — FSM may be
       stale relative to a server-side close).
    4. Reject stickers / unsupported media types.
    5. Record + mirror the message.
    """
    if message.from_user is None:
        return
    text_value = message.text or ""
    if text_value.startswith("/"):
        return  # let dedicated command routers handle it.

    tg_id = message.from_user.id
    user_id = (db_user or {}).get("id")

    if await _is_flooded(redis, tg_id):
        flood_text = await texts.get("support_flood_limit")
        await message.answer(flood_text)
        return

    try:
        ticket = await api.get_active_ticket(tg_id)
    except BackendUnavailableError as exc:
        await report_backend_unavailable(
            message, api=api, texts=texts, user_id=user_id,
            error=exc, event="support_msg_active_ticket_backend_unavailable",
        )
        return
    except Exception as exc:  # noqa: BLE001
        await report_unexpected(
            message, api=api, texts=texts, user_id=user_id,
            error=exc, event="support_msg_active_ticket_unexpected",
        )
        return

    if ticket is None:
        # Backend says "no open ticket" but FSM thinks otherwise — reset.
        await state.clear()
        nudge = await texts.get("support_outside_ticket_nudge")
        await message.answer(nudge)
        return

    ticket_id = ticket.get("id")
    if not isinstance(ticket_id, int):
        log.warning("support.ticket_missing_id", ticket=ticket)
        await state.clear()
        await message.answer(await texts.get("support_outside_ticket_nudge"))
        return

    # ---- reject stickers --------------------------------------------------
    if message.sticker is not None:
        await message.answer(await texts.get("support_sticker_rejected"))
        return

    # ---- reject unsupported media ----------------------------------------
    if (
        message.document is not None
        or message.video is not None
        or message.audio is not None
        or message.voice is not None
        or message.animation is not None
        or message.video_note is not None
    ):
        await message.answer(await texts.get("support_unsupported_media"))
        return

    # ---- text -------------------------------------------------------------
    if message.photo:
        # Largest photo — last in the array.
        photo = message.photo[-1]
        caption = message.caption or None
        try:
            await api.record_ticket_message(
                ticket_id,
                direction="from_user",
                message_type="photo",
                text=caption,
                photo_file_id=photo.file_id,
                tg_message_id=message.message_id,
            )
        except (BackendUnavailableError, BackendClientError) as exc:
            log.warning("support.record_photo_failed", error=str(exc))
        helper_user: dict[str, Any] | Any = (
            db_user if isinstance(db_user, dict) else message.from_user
        )
        try:
            await support_topic_helper.forward_user_message_to_topic(
                bot, api, settings, ticket, helper_user, message, texts,
            )
        except Exception as exc:  # noqa: BLE001 — best-effort mirror.
            log.warning("support.forward_photo_failed", error=str(exc))
        return

    if not text_value:
        # Defensive: anything else (poll/contact/location/...) we don't handle.
        await message.answer(await texts.get("support_unsupported_media"))
        return

    try:
        await api.record_ticket_message(
            ticket_id,
            direction="from_user",
            message_type="text",
            text=text_value,
            tg_message_id=message.message_id,
        )
    except (BackendUnavailableError, BackendClientError) as exc:
        log.warning("support.record_text_failed", error=str(exc))
        await bot_log(
            api,
            level=LOG_LEVEL_WARNING,
            event="support_record_text_failed",
            user_id=user_id,
            message=str(exc),
            context={"ticket_id": ticket_id},
        )

    helper_user_text: dict[str, Any] | Any = (
        db_user if isinstance(db_user, dict) else message.from_user
    )
    try:
        await support_topic_helper.forward_user_message_to_topic(
            bot, api, settings, ticket, helper_user_text, message, texts,
        )
    except Exception as exc:  # noqa: BLE001 — best-effort mirror.
        log.warning("support.forward_text_failed", error=str(exc))


# ----------------------------- outside-ticket nudge -------------------------


@router.message(
    StateFilter(None),
    F.chat.type == "private",
    F.text & ~F.text.startswith("/"),
)
async def msg_unsolicited_text(
    message: Message,
    texts: TextService,
) -> None:
    """User sent a plain message while NOT in any FSM state.

    This is the catch-all from stage4.md §5 — direct them to open a ticket
    instead of letting the message vanish silently. Slash-commands and
    state-bound messages are excluded by the filter so this only triggers
    for ad-hoc free-text DMs.

    Restricted to private chats — admin replies inside the support forum
    group must NOT trigger this nudge (they're handled by the dedicated
    admin-side router that listens for replies inside the support group).

    Note: this handler MUST be registered after every other state-bound
    handler in this router (and after Stage 2/3 state-bound handlers in
    other routers, which is enforced by ``main.py`` registration order).
    """
    nudge = await texts.get("support_outside_ticket_nudge")
    await message.answer(nudge)
