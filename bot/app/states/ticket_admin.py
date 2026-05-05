"""FSM state group for the admin-side ban-with-reason flow.

States:
- ``awaiting_ban_reason`` — admin clicked the "❌ Заблокировать" button under
  a user message; the bot prompted in-topic for a reason and is waiting for
  one free-text message (or the ``tadm:ban_cancel`` callback / ``/cancel``).

Payload (in ``FSMContext.update_data``):
- ``ticket_id`` — int, primary key of the ticket whose author is being banned.
- ``user_tg_id`` — int, target user's Telegram id (used to deliver the ban).
- ``user_id`` — int, backend user id (for ``support_topics`` lookups).
- ``user_username`` — str | None, used in the in-topic confirmation message.
- ``thread_id`` — int, message_thread_id of the support topic.
- ``prompt_message_id`` — int, message id of the bot's "введите причину"
  prompt; handlers delete or edit it after the flow ends.
"""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class AdminTicketStates(StatesGroup):
    """States traversed when an admin runs the ban-with-reason wizard."""

    awaiting_ban_reason = State()
