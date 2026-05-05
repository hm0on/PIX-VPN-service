"""Keyboards for the Stage 4 ticket flow (support + idea).

Covers four distinct surfaces:
- Inline keyboards on the "no active ticket" cards (one for support, one for
  idea) → trigger the create-ticket callback.
- A persistent reply keyboard with the single "Закрыть тикет" button shown to
  the user while their ticket is open. Reply keyboards can't be attached to
  inline-keyboard messages, so handlers send a tiny plain-text helper message
  to mount them.
- An inline confirm keyboard (Yes/No) that follows the close-button tap.
- ``remove_kb`` — a small helper returning :class:`ReplyKeyboardRemove` to
  drop the persistent keyboard once the ticket transitions to closed.
"""

from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

# Public callback data constants — handlers and tests reference these so we
# only have to spell them in one place.
CB_TICKET_CREATE_SUPPORT = "ticket:create:support"
CB_TICKET_CREATE_IDEA = "ticket:create:idea"
CB_TICKET_CLOSE_YES = "ticket:close:yes"
CB_TICKET_CLOSE_NO = "ticket:close:no"

# Reply-button text for "Закрыть тикет" — must match exactly what
# :func:`ticket_active_reply_kb` produces, since handlers filter on this text.
CLOSE_TICKET_BUTTON_TEXT = "Закрыть тикет"


def support_no_ticket_kb() -> InlineKeyboardMarkup:
    """Inline keyboard for the "Поддержка" card when no open ticket exists."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Создать тикет",
                    callback_data=CB_TICKET_CREATE_SUPPORT,
                )
            ],
            [InlineKeyboardButton(text="← Назад", callback_data="main_menu")],
        ]
    )


def idea_no_ticket_kb() -> InlineKeyboardMarkup:
    """Inline keyboard for the "Предложить идею" card when no open ticket."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Предложить идею",
                    callback_data=CB_TICKET_CREATE_IDEA,
                )
            ],
            [InlineKeyboardButton(text="← Назад", callback_data="main_menu")],
        ]
    )


def ticket_active_reply_kb() -> ReplyKeyboardMarkup:
    """Persistent reply keyboard mounted on the user while a ticket is open."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=CLOSE_TICKET_BUTTON_TEXT)]],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


def ticket_close_confirm_kb() -> InlineKeyboardMarkup:
    """Inline confirm/cancel keyboard for the close-ticket flow."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Да, закрыть", callback_data=CB_TICKET_CLOSE_YES
                ),
                InlineKeyboardButton(
                    text="Отмена", callback_data=CB_TICKET_CLOSE_NO
                ),
            ]
        ]
    )


def remove_kb() -> ReplyKeyboardRemove:
    """Return a fresh :class:`ReplyKeyboardRemove` to drop the ticket KB."""
    return ReplyKeyboardRemove()
