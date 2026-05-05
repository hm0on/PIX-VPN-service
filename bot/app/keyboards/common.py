"""Shared inline keyboards: back-to-menu, subscription check.

Two flavours of label resolution coexist here on purpose:

- ``back_kb`` stays **synchronous** because it's used by ~20 handlers in
  hot paths and threading ``await text_service.get_button(...)`` through
  every one of them was a churn-for-no-gain refactor. Instead it accepts an
  explicit ``text`` override (which most handlers don't pass) and falls
  back to a static label from :data:`app.utils.texts._BUTTON_FALLBACKS` —
  the same string the migration seeded into the database. Admins who want
  to rename it can do so for the keys they care about
  (``btn.common.back`` / ``btn.payment.cancel`` / etc.) and call those
  builders that are async-aware (the major keyboards under
  ``main_menu``/``profile``/``catalog``/``ticket``).

- ``subscription_check_kb`` is async — it's only called from one spot in
  the channel-gate middleware, and the labels there are exactly the ones
  operators most often want to localise (the channel-subscription gate is
  the very first thing some users see).
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.utils.texts import TextService, _BUTTON_FALLBACKS


def back_kb(
    callback: str = "main_menu",
    text: str | None = None,
    *,
    text_key: str = "btn.common.back",
) -> InlineKeyboardMarkup:
    """A single "Back" button. Default target: main menu.

    ``text`` (legacy positional, still accepted) wins over ``text_key`` for
    callers that want to set the label inline. When neither is given we use
    the fallback for ``btn.common.back`` from :mod:`app.utils.texts` — that
    matches what the seeded row in the database holds, so admins can rename
    it via the texts editor (the change propagates the next time the bot's
    in-memory cache refreshes, ≤60 s).
    """
    if text is None:
        text = _BUTTON_FALLBACKS.get(text_key, "← Назад")
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=text, callback_data=callback)]]
    )


async def subscription_check_kb(
    channel_url: str, text_service: TextService
) -> InlineKeyboardMarkup:
    """Two-row keyboard for the channel-subscription gate.

    Row 1: external "Подписаться" link (label = ``btn.common.subscribe``).
    Row 2: callback "Я подписался ✅" (label = ``btn.common.subscribed``)
           → re-checks via the ``check_sub`` handler.
    """
    sub_label, sub_icon = await text_service.get_button("btn.common.subscribe")
    done_label, done_icon = await text_service.get_button("btn.common.subscribed")
    sub_extra: dict[str, object] = (
        {"icon_custom_emoji_id": sub_icon} if sub_icon else {}
    )
    done_extra: dict[str, object] = (
        {"icon_custom_emoji_id": done_icon} if done_icon else {}
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=sub_label, url=channel_url, **sub_extra  # type: ignore[arg-type]
                )
            ],
            [
                InlineKeyboardButton(
                    text=done_label,
                    callback_data="check_sub",
                    **done_extra,  # type: ignore[arg-type]
                )
            ],
        ]
    )
