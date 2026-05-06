"""«О проекте» section handler.

Replaces the old stubbed ``about`` callback. Reads the body text and the
three button rows from the ``texts`` table (kind=``button`` with ``url``
populated) so admins can rename labels, swap URLs and replace the message
body without redeploying. The keyboard layout is fixed in code:

    Row 1: [Политика конфиденциальности]
    Row 2: [Пользовательское соглашение]
    Row 3: [Наш канал]
    Row 4: [← Назад]

Each of the first three buttons becomes a URL button when its text row has
``url`` set. If an admin clears the URL, the row falls back to a plain
callback button that returns the user to the main menu — clearing a URL
should never break the keyboard.
"""

from __future__ import annotations

from aiogram import Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from app.handlers._common import safe_edit_or_send_media
from app.utils.texts import TextService

router = Router(name="about")


_ABOUT_BUTTON_KEYS: tuple[str, ...] = (
    "btn.about.privacy",
    "btn.about.terms",
    "btn.about.channel",
)


async def _build_keyboard(texts: TextService) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for key in _ABOUT_BUTTON_KEYS:
        label, icon, url = await texts.get_url_button(key)
        extra: dict[str, object] = {}
        if icon:
            extra["icon_custom_emoji_id"] = icon
        if url:
            btn = InlineKeyboardButton(text=label, url=url, **extra)  # type: ignore[arg-type]
        else:
            # Fallback: admin cleared the URL — keep the button visible but
            # make it a no-op that returns to main menu, so the keyboard
            # never ends up with a button Telegram will reject.
            btn = InlineKeyboardButton(
                text=label, callback_data="main_menu", **extra  # type: ignore[arg-type]
            )
        rows.append([btn])

    back_label, back_icon = await texts.get_button("btn.common.back")
    back_extra: dict[str, object] = (
        {"icon_custom_emoji_id": back_icon} if back_icon else {}
    )
    rows.append(
        [
            InlineKeyboardButton(
                text=back_label, callback_data="main_menu", **back_extra  # type: ignore[arg-type]
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(lambda c: c.data == "about")
async def cb_about(callback: CallbackQuery, texts: TextService) -> None:
    """Render the «О проекте» screen with body text and link buttons."""
    entry = await texts.get_entry("about")
    kb = await _build_keyboard(texts)
    await safe_edit_or_send_media(callback, entry, reply_markup=kb)
