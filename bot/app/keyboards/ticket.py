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

from app.utils.texts import TextService, _BUTTON_FALLBACKS

from app.utils.texts import TextService, _BUTTON_FALLBACKS

# Public callback data constants — handlers and tests reference these so we
# only have to spell them in one place.
CB_TICKET_CREATE_SUPPORT = "ticket:create:support"
CB_TICKET_CREATE_IDEA = "ticket:create:idea"
CB_TICKET_CLOSE_YES = "ticket:close:yes"
CB_TICKET_CLOSE_NO = "ticket:close:no"

# Reply-button text for "Закрыть тикет" — must match exactly what
# :func:`ticket_active_reply_kb` produces, since handlers filter on this text.
CLOSE_TICKET_BUTTON_TEXT = "Закрыть тикет"


async def support_no_ticket_kb(
    text_service: TextService,
) -> InlineKeyboardMarkup:
    """Inline keyboard for the "Поддержка" card when no open ticket exists."""
    create_label, create_icon = await text_service.get_button(
        "btn.ticket.create_support"
    )
    back_label, back_icon = await text_service.get_button("btn.common.back")
    create_extra: dict[str, object] = (
        {"icon_custom_emoji_id": create_icon} if create_icon else {}
    )
    back_extra: dict[str, object] = (
        {"icon_custom_emoji_id": back_icon} if back_icon else {}
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=create_label,
                    callback_data=CB_TICKET_CREATE_SUPPORT,
                    **create_extra,  # type: ignore[arg-type]
                )
            ],
            [
                InlineKeyboardButton(
                    text=back_label,
                    callback_data="main_menu",
                    **back_extra,  # type: ignore[arg-type]
                )
            ],
        ]
    )


async def idea_no_ticket_kb(
    text_service: TextService,
) -> InlineKeyboardMarkup:
    """Inline keyboard for the "Предложить идею" card when no open ticket."""
    create_label, create_icon = await text_service.get_button(
        "btn.ticket.create_idea"
    )
    back_label, back_icon = await text_service.get_button("btn.common.back")
    create_extra: dict[str, object] = (
        {"icon_custom_emoji_id": create_icon} if create_icon else {}
    )
    back_extra: dict[str, object] = (
        {"icon_custom_emoji_id": back_icon} if back_icon else {}
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=create_label,
                    callback_data=CB_TICKET_CREATE_IDEA,
                    **create_extra,  # type: ignore[arg-type]
                )
            ],
            [
                InlineKeyboardButton(
                    text=back_label,
                    callback_data="main_menu",
                    **back_extra,  # type: ignore[arg-type]
                )
            ],
        ]
    )


def ticket_active_reply_kb() -> ReplyKeyboardMarkup:
    """Persistent reply keyboard mounted on the user while a ticket is open.

    Stays sync — :class:`ReplyKeyboardMarkup` is a different surface than
    inline buttons (it shows up in the user's keyboard area, not under the
    message), and this single label is also matched by an aiogram filter on
    the literal :data:`CLOSE_TICKET_BUTTON_TEXT`. Renaming it via the texts
    editor would silently break that filter, so we deliberately leave this
    one hardcoded. If you need to localise it, also update
    :data:`CLOSE_TICKET_BUTTON_TEXT` and the filter in
    ``handlers/support.py``.
    """
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=CLOSE_TICKET_BUTTON_TEXT)]],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


async def ticket_close_confirm_kb(
    text_service: TextService,
) -> InlineKeyboardMarkup:
    """Inline confirm/cancel keyboard for the close-ticket flow."""
    yes_label, yes_icon = await text_service.get_button("btn.ticket.close_yes")
    no_label, no_icon = await text_service.get_button("btn.ticket.close_no")
    yes_extra: dict[str, object] = (
        {"icon_custom_emoji_id": yes_icon} if yes_icon else {}
    )
    no_extra: dict[str, object] = (
        {"icon_custom_emoji_id": no_icon} if no_icon else {}
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=yes_label,
                    callback_data=CB_TICKET_CLOSE_YES,
                    **yes_extra,  # type: ignore[arg-type]
                ),
                InlineKeyboardButton(
                    text=no_label,
                    callback_data=CB_TICKET_CLOSE_NO,
                    **no_extra,  # type: ignore[arg-type]
                ),
            ]
        ]
    )


# ``_BUTTON_FALLBACKS`` is re-exported so other keyboards files can pull
# the same plain-string defaults without re-importing the private name.
__all__ = [
    "CB_TICKET_CREATE_SUPPORT",
    "CB_TICKET_CREATE_IDEA",
    "CB_TICKET_CLOSE_YES",
    "CB_TICKET_CLOSE_NO",
    "CLOSE_TICKET_BUTTON_TEXT",
    "support_no_ticket_kb",
    "idea_no_ticket_kb",
    "ticket_active_reply_kb",
    "ticket_close_confirm_kb",
    "remove_kb",
    "_BUTTON_FALLBACKS",
]


def remove_kb() -> ReplyKeyboardRemove:
    """Return a fresh :class:`ReplyKeyboardRemove` to drop the ticket KB."""
    return ReplyKeyboardRemove()
