"""Stub callback handlers for sections not implemented yet.

Each stub answers with the `section_in_development` text and a "back to main
menu" button. Real implementations land in:
- catalog → Stage 2 (real handler in app.handlers.catalog)
- profile → Stage 2 (real handler in app.handlers.profile)
- support → Stage 4 (real handler in app.handlers.support)
- promo   → Stage 3
- idea    → Stage 4 (real handler in app.handlers.support)
- about   → Stage 1 (could already be a real text — left as stub on purpose
            to keep Stage 1 minimal; switch to a dedicated text key when ready)
"""

from __future__ import annotations

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery

from app.keyboards.common import back_kb
from app.utils.logging import get_logger
from app.utils.texts import TextService

router = Router(name="stubs")
log = get_logger("bot.handlers.stubs")


# `catalog` and `profile` removed: handled by real routers (catalog.py /
# profile.py). `support` and `idea` removed in Stage 4 (handled by support.py).
# The remaining stubs cover the still-unimplemented sections.
_STUB_CALLBACKS = frozenset({"about"})


@router.callback_query(lambda c: c.data in _STUB_CALLBACKS)
async def cb_stub(callback: CallbackQuery, texts: TextService) -> None:
    """Single handler for every "in development" section."""
    text = await texts.get("section_in_development")
    kb = back_kb(callback="main_menu")

    await callback.answer()
    if callback.message is None:
        return
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest:
        # Source message wasn't editable (e.g. it was a photo/caption) — fall
        # back to sending a new message.
        await callback.message.answer(text, reply_markup=kb)
