"""Main menu inline keyboard."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def make_button(
    text: str,
    *,
    callback_data: str | None = None,
    url: str | None = None,
    color: str | None = None,  # noqa: ARG001 — reserved for Bot API additions
) -> InlineKeyboardButton:
    """Build an InlineKeyboardButton.

    TODO(Stage 1+): Telegram does **not** support coloring inline buttons via
    Bot API yet (KeyboardButtonColor exists only for *reply* keyboards in 7.10+).
    The ``color`` argument is kept here so call-sites can describe intent
    declaratively, and we will plug it in once aiogram exposes the field.
    """
    if callback_data is not None:
        return InlineKeyboardButton(text=text, callback_data=callback_data)
    if url is not None:
        return InlineKeyboardButton(text=text, url=url)
    raise ValueError("make_button requires either callback_data or url")


def main_menu_kb() -> InlineKeyboardMarkup:
    """Layout from `questions.md` → "Как я вижу визуал" / Main menu.

    Row 1: [Каталог 🟦] [Профиль]
    Row 2: [Поддержка] [Промокод]
    Row 3: [Предложить идею]
    Row 4: [О проекте]
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                # 🟦 hints at the future "blue" highlight; visual color TBD by Bot API.
                make_button("Каталог 🟦", callback_data="catalog", color="blue"),
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
