"""FREE-trial activation handler.

Two entry points share the same activation logic:

1. ``cb_tariff`` (in ``handlers/catalog.py``) — when the user clicks the
   FREE tariff card inside the catalog screen. Kept for backwards
   compatibility with users who arrive via the catalog flow.
2. ``cb_free_trial`` (here) — the new "🎁 5 дней бесплатно" button on
   ``main_menu``, added in the conversion-pack 2026-05-13. This skips the
   catalog entirely so a brand-new user can claim the trial in one click.

The activation routine lives in :func:`activate_free_trial` and is called
from both call-sites.
"""

from __future__ import annotations

from typing import Any

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.api_client import BackendClient
from app.config import Settings
from app.handlers._common import (
    report_backend_unavailable,
    report_unexpected,
    safe_edit_or_answer,
    safe_edit_or_send_media,
)
from app.keyboards.catalog import key_issued_kb
from app.keyboards.common import back_kb
from app.utils.errors import BackendClientError, BackendUnavailableError
from app.utils.logging import LOG_LEVEL_INFO, bot_log, get_logger
from app.utils.texts import TextService

router = Router(name="free_trial")
log = get_logger("bot.handlers.free_trial")


async def activate_free_trial(
    callback: CallbackQuery,
    *,
    api: BackendClient,
    texts: TextService,
    settings: Settings,
    tg_id: int,
    user_id: int | None,
) -> None:
    """Activate the FREE trial and edit the source message in-place.

    UX:

    1. Edit the source message to the ``key_issuing`` placeholder
       (⏳ Выдаём ключ...) for immediate feedback while NorthLine
       provisions the key.
    2. On success — edit to ``key_issued_free_trial`` with the
       ``key_issued_kb`` keyboard.

    The backend deliberately does NOT enqueue an outbox message for the
    free-trial flow — this synchronous edit IS the delivery. See the
    matching note in ``backend/app/services/free_trial_service.py``.

    Backend errors of interest:
    - ``free_trial_already_used`` → friendly explanation + back.
    - ``vpn_provider_unavailable`` → "try later" + back.
    """
    placeholder_text = await texts.get("key_issuing")
    await safe_edit_or_answer(callback, placeholder_text, reply_markup=None)

    try:
        result = await api.activate_free_trial(tg_id)
    except BackendClientError as exc:
        text_key, log_event = "unexpected_error", "free_trial_failed"
        if exc.error_code == "free_trial_already_used":
            text_key = "free_trial_already_used"
            log_event = "free_trial_already_used"
        elif exc.error_code == "vpn_provider_unavailable":
            text_key = "vpn_provider_unavailable"
            log_event = "vpn_provider_unavailable"
        text = await texts.get(text_key)
        await safe_edit_or_answer(
            callback, text, reply_markup=back_kb(callback="catalog")
        )
        await bot_log(
            api,
            level=LOG_LEVEL_INFO,
            event=log_event,
            user_id=user_id,
            message=exc.detail[:300],
            context={"error_code": exc.error_code, "tg_id": tg_id},
        )
        return
    except BackendUnavailableError as exc:
        await report_backend_unavailable(
            callback,
            api=api,
            texts=texts,
            user_id=user_id,
            error=exc,
            event="free_trial_backend_unavailable",
        )
        return
    except Exception as exc:  # noqa: BLE001
        await report_unexpected(
            callback, api=api, texts=texts, user_id=user_id,
            error=exc, event="free_trial_unexpected",
        )
        return

    sub_data: dict[str, Any] = result.get("subscription") or {}
    sub_key_url = sub_data.get("key_url", "") or ""
    entry = await texts.get_entry(
        "key_issued_free_trial",
        key_url=sub_key_url,
        # Defaults bumped 3→5 days / 1→2 devices in conversion-pack
        # 2026-05-13 to match the new FREE-tariff seed.
        days=sub_data.get("days", 5),
        devices=sub_data.get("devices", 2),
        subscription_id=sub_data.get("id", ""),
    )
    await safe_edit_or_send_media(
        callback,
        entry,
        reply_markup=await key_issued_kb(
            settings.HOWTO_CONNECT_URL,
            text_service=texts,
            key_url=sub_key_url,
        ),
    )
    await bot_log(
        api,
        level=LOG_LEVEL_INFO,
        event="free_trial_issued",
        user_id=user_id,
        message="Free trial issued",
        context={
            "tg_id": tg_id,
            "subscription_id": sub_data.get("id"),
        },
    )


@router.callback_query(F.data == "free_trial")
async def cb_free_trial(
    callback: CallbackQuery,
    api: BackendClient,
    texts: TextService,
    settings: Settings,
    db_user: dict[str, Any] | None = None,
) -> None:
    """Top-level "🎁 5 дней бесплатно" button on main_menu."""
    if callback.from_user is None:
        await callback.answer()
        return
    tg_id = callback.from_user.id
    user_id = (db_user or {}).get("id")
    await activate_free_trial(
        callback,
        api=api,
        texts=texts,
        settings=settings,
        tg_id=tg_id,
        user_id=user_id,
    )
