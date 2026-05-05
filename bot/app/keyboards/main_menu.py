"""Main menu inline keyboard."""

from __future__ import annotations

from aiogram.enums import ButtonStyle
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

_COLOR_TO_STYLE: dict[str, ButtonStyle] = {
    "blue": ButtonStyle.PRIMARY,
    "primary": ButtonStyle.PRIMARY,
    "green": ButtonStyle.SUCCESS,
    "success": ButtonStyle.SUCCESS,
    "red": ButtonStyle.DANGER,
    "danger": ButtonStyle.DANGER,
}


def make_button(
    text: str,
    *,
    callback_data: str | None = None,
    url: str | None = None,
    style: ButtonStyle | None = None,
    color: str | None = None,
) -> InlineKeyboardButton:
    """Build an InlineKeyboardButton.

    Since Bot API 9.4 (aiogram 3.25+), inline buttons support a ``style``
    parameter (``ButtonStyle.PRIMARY`` / ``SUCCESS`` / ``DANGER``). Older
    Telegram clients render them as default — no error, just no color.

    ``color`` is a backwards-compatible string alias ("blue" / "green" / "red")
    used by older call-sites; it maps to the corresponding ``ButtonStyle``.
    Explicit ``style=`` always wins.
    """
    if style is None and color is not None:
        style = _COLOR_TO_STYLE.get(color.lower())
    if callback_data is not None:
        return InlineKeyboardButton(text=text, callback_data=callback_data, style=style)
    if url is not None:
        return InlineKeyboardButton(text=text, url=url, style=style)
    raise ValueError("make_button requires either callback_data or url")


def main_menu_kb() -> InlineKeyboardMarkup:
    """Layout from `questions.md` → "Как я вижу визуал" / Main menu.

    Row 1: [Каталог (синяя)] [Профиль]
    Row 2: [Поддержка] [Промокод]
    Row 3: [Предложить идею]
    Row 4: [О проекте]
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                make_button("Каталог", callback_data="catalog", style=ButtonStyle.PRIMARY),
                make_button("Профиль", callback_data="profile"),
            ],
            [
                make_button("Поддержка", callback_data="support"),
                make_button("Промокод", callback_data="promo"),
            ],
            [make_button("Предложить идею", callback_data="idea")],
            [make_button("О проекте", callback_data="about")],
        ]
    )
