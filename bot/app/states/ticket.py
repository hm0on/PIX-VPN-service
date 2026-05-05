"""FSM state group for the Stage 4 ticket (support / idea) flow.

States:
- ``in_ticket`` — user has an open ticket; messages and the "Закрыть тикет"
  reply-keyboard button are routed to the support handler.
- ``awaiting_close_confirm`` — user pressed "Закрыть тикет"; we are waiting
  for them to confirm via inline ``[Да, закрыть] [Отмена]``.

Payload (in ``FSMContext.update_data``):
- ``ticket_id`` — int, primary key of the open ticket.
- ``ticket_code`` — str, e.g. ``TCK-A1B2C3`` — used in confirmations.
- ``ticket_kind`` — ``"support"`` / ``"idea"`` — used by message-formatting.
"""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class TicketStates(StatesGroup):
    """States traversed while the user is inside an open support ticket."""

    in_ticket = State()
    awaiting_close_confirm = State()
