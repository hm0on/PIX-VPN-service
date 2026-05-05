"""Inline keyboards for the Stage 4 admin-side ticket flow.

These are attached to the *user → topic* envelope and to the in-topic ban
prompt:

- :func:`ticket_admin_actions_kb` — placed under every user message that the
  user-side router mirrors into the topic. Lets admins ban the author or
  close the ticket directly from the chat.
- :func:`ban_reason_cancel_kb` — the single-button "cancel" keyboard sent
  alongside the "введите причину" prompt; ack via the ``tadm:ban_cancel``
  callback.

Callback-data constants are exported so handlers and tests share one
spelling. Format: ``tadm:<action>:<ticket_id>`` for action buttons,
``tadm:<action>`` for global ones.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

# Action prefix and full callbacks. Handlers register on ``startswith``.
CB_PREFIX = "tadm"
CB_BAN = f"{CB_PREFIX}:ban"
CB_CLOSE = f"{CB_PREFIX}:close"
CB_BAN_CANCEL = f"{CB_PREFIX}:ban_cancel"


def ticket_admin_actions_kb(ticket_id: int) -> InlineKeyboardMarkup:
    """Two-button row attached under every mirrored user message in topics."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="❌ Заблокировать",
                    callback_data=f"{CB_BAN}:{ticket_id}",
                ),
                InlineKeyboardButton(
                    text="✅ Закрыть тикет",
                    callback_data=f"{CB_CLOSE}:{ticket_id}",
                ),
            ]
        ]
    )


def ban_reason_cancel_kb() -> InlineKeyboardMarkup:
    """Single ``Отмена`` button attached to the ban-reason prompt message."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data=CB_BAN_CANCEL)]
        ]
    )
