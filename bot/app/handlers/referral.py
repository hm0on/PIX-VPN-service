"""Referral program screen — Stage 3.

Single callback (``referral_program``) that fetches stats from the backend
and renders an HTML card with the user's referral link, invited count, and
total earnings. Sharing uses Telegram's ``switch_inline_query`` so the user
picks a chat and Telegram pre-fills the message with a short pitch.

The bot is intentionally dumb here: it does not know its own username.
Backend computes ``ref_link`` (e.g. ``https://t.me/<bot>?start=ref_42``)
and returns it in the stats payload — that's the single source of truth.
"""

from __future__ import annotations

from typing import Any

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.api_client import BackendClient
from app.handlers._common import (
    report_backend_unavailable,
    report_unexpected,
    safe_edit_or_answer,
)
from app.keyboards.profile import referral_kb
from app.utils.errors import BackendUnavailableError
from app.utils.logging import get_logger
from app.utils.texts import TextService

router = Router(name="referral")
log = get_logger("bot.handlers.referral")


@router.callback_query(F.data == "referral_program")
async def cb_referral_program(
    callback: CallbackQuery,
    api: BackendClient,
    texts: TextService,
    db_user: dict[str, Any] | None = None,
) -> None:
    """Render the referral program card with personal stats."""
    if callback.from_user is None:
        await callback.answer()
        return

    tg_id = callback.from_user.id
    user_id = (db_user or {}).get("id")

    try:
        stats = await api.get_referral_stats(tg_id)
    except BackendUnavailableError as exc:
        await report_backend_unavailable(
            callback, api=api, texts=texts, user_id=user_id,
            error=exc, event="referral_stats_backend_unavailable",
        )
        return
    except Exception as exc:  # noqa: BLE001
        await report_unexpected(
            callback, api=api, texts=texts, user_id=user_id,
            error=exc, event="referral_stats_unexpected",
        )
        return

    invited = int(stats.get("invited", 0) or 0)
    earned_kop = int(stats.get("earned_kopecks", 0) or 0)
    ref_link = str(stats.get("ref_link", "") or "")

    # Backend's ``referral_program_screen`` template uses ``{invited}``
    # (see backend/app/seeds.py); pass ``count`` too so older seeds stay
    # tolerant if redeployed without re-seed.
    text = await texts.get(
        "referral_program_screen",
        ref_link=ref_link,
        invited=invited,
        count=invited,
        earned=earned_kop // 100,
    )
    # ``share_text`` is what Telegram pre-fills when the user picks a chat
    # via ``switch_inline_query``. Keep it short — it's seen as a draft.
    share_text = (
        f"Подключи безлимитный VPN со скидкой 10% на первую покупку: {ref_link}"
        if ref_link
        else "Подключи безлимитный VPN со скидкой 10% на первую покупку!"
    )
    await safe_edit_or_answer(
        callback, text, reply_markup=referral_kb(ref_link, share_text)
    )
