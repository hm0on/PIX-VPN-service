"""FSM state groups for the Stage 2 purchase + top-up flows.

The states themselves carry no data — payload (``tariff_id``, ``duration_id``,
``amount_kopecks``, ``payment_id``) lives in ``FSMContext.update_data(...)``.

Notes on lifecycle:
- ``PurchaseStates.promo_input`` is reached straight after the user picks a
  duration. Stage 2 has no promo logic, so a free-text message in this state
  responds with "section in development" and the user clicks "Нет промокода"
  to proceed. Stage 3 will add real promo handling here.
- ``PurchaseStates.awaiting_payment`` is "passive" on Stage 2: after the bot
  shows the "Оплатить" button the actual key-issued message comes from the
  outbox worker (triggered by the provider webhook), not from the bot. The
  state is kept so that if the user comes back later we can recognise it.
  Redis FSM TTL handles cleanup if they never come back.
"""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class PurchaseStates(StatesGroup):
    """States traversed when buying a paid tariff."""

    promo_input = State()         # Stage 3 — здесь будет ввод промокода
    payment_method = State()      # выбор СБП / CryptoBot / крипта / баланс
    awaiting_payment = State()    # invoice отправлен, ждём webhook от провайдера


class TopupStates(StatesGroup):
    """States traversed when topping up balance from the profile."""

    amount_input = State()        # юзер вводит сумму в рублях (минимум 10)
    payment_method = State()      # выбор СБП / CryptoBot / крипта


class ExtendStates(StatesGroup):
    """States traversed when extending an existing active subscription.

    Stored payload (in ``FSMContext.update_data``):
    - ``subscription_id`` — sub being extended
    - ``duration_id`` — selected duration (same tariff as ``subscription_id``)
    - ``promo_id`` — optional discount-promo id (set by promo flow)
    - ``payment_id`` — set after invoice creation (awaiting_payment)

    The flow mirrors :class:`PurchaseStates` but with extension-specific
    callbacks (``ext_pay``, ``ext_promo_skip``…) so the dispatcher can route
    them without ambiguity.
    """

    promo_input = State()
    payment_method = State()
    awaiting_payment = State()
