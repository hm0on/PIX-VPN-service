"""Balance top-up flow.

Three steps:
1. ``topup`` callback → enter :pyattr:`TopupStates.amount_input`, prompt for
   amount in rubles (minimum 10 ₽).
2. Free-text message in that state → parse → store amount in kopecks → enter
   :pyattr:`TopupStates.payment_method`, show provider picker.
3. ``topup_pay:{provider}`` → create invoice via backend, render the
   "Оплатить" button. Webhook → outbox → worker delivers the
   "balance topped up" message asynchronously.
"""

from __future__ import annotations

from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.api_client import BackendClient
from app.handlers._common import (
    report_backend_unavailable,
    report_unexpected,
    safe_edit_or_answer,
)
from app.keyboards.catalog import payment_link_kb
from app.keyboards.common import back_kb
from app.keyboards.profile import topup_back_kb, topup_methods_kb
from app.states.purchase import TopupStates
from app.utils.errors import BackendClientError, BackendUnavailableError
from app.utils.logging import LOG_LEVEL_INFO, LOG_LEVEL_WARNING, bot_log, get_logger
from app.utils.texts import TextService

router = Router(name="topup")
log = get_logger("bot.handlers.topup")


_MIN_RUB = 10
_TOPUP_PROVIDERS: frozenset[str] = frozenset(
    {"platega_sbp", "platega_crypto", "cryptobot"}
)


@router.callback_query(F.data == "topup")
async def cb_topup_start(
    callback: CallbackQuery,
    texts: TextService,
    state: FSMContext,
) -> None:
    """Begin the top-up flow — ask the user for an amount in rubles."""
    await state.clear()
    await state.set_state(TopupStates.amount_input)

    text = await texts.get("topup_amount_prompt", min_amount=_MIN_RUB)
    await safe_edit_or_answer(callback, text, reply_markup=await topup_back_kb(texts))


@router.message(TopupStates.amount_input)
async def msg_topup_amount(
    message: Message,
    api: BackendClient,
    texts: TextService,
    state: FSMContext,
    db_user: dict[str, Any] | None = None,
) -> None:
    """Parse the typed amount and advance to the payment-method picker."""
    raw = (message.text or "").strip().replace(" ", "").replace(",", ".")
    user_id = (db_user or {}).get("id")

    try:
        # Accept "100", "100.0" — anything fractional rounds *down*.
        rub = int(float(raw))
    except (TypeError, ValueError):
        text = await texts.get("topup_invalid_amount", min_amount=_MIN_RUB)
        await message.answer(text, reply_markup=await topup_back_kb(texts))
        return

    if rub < _MIN_RUB:
        text = await texts.get("topup_min_amount", min_amount=_MIN_RUB)
        await message.answer(text, reply_markup=await topup_back_kb(texts))
        return

    amount_kopecks = rub * 100
    await state.update_data(amount_kopecks=amount_kopecks)
    await state.set_state(TopupStates.payment_method)

    text = await texts.get("topup_method_prompt", amount=rub)
    await message.answer(text, reply_markup=await topup_methods_kb(texts))

    await bot_log(
        api,
        level=LOG_LEVEL_INFO,
        event="topup_amount_set",
        user_id=user_id,
        message="User selected top-up amount",
        context={"amount_kopecks": amount_kopecks},
    )


@router.callback_query(F.data.startswith("topup_pay:"), TopupStates.payment_method)
async def cb_topup_pay(
    callback: CallbackQuery,
    api: BackendClient,
    texts: TextService,
    state: FSMContext,
    db_user: dict[str, Any] | None = None,
) -> None:
    """Create the top-up invoice via backend and show the pay button."""
    if callback.data is None or callback.from_user is None:
        await callback.answer()
        return

    provider = callback.data.split(":", 1)[1] if ":" in callback.data else ""
    if provider not in _TOPUP_PROVIDERS:
        await callback.answer()
        return

    tg_id = callback.from_user.id
    user_id = (db_user or {}).get("id")

    data = await state.get_data()
    amount_raw = data.get("amount_kopecks")
    if amount_raw is None:
        await callback.answer("Сумма не выбрана, начните заново", show_alert=True)
        await state.clear()
        return
    amount_kopecks = int(amount_raw)

    try:
        result = await api.create_topup(tg_id, amount_kopecks, provider)
    except BackendClientError as exc:
        text_key = "unexpected_error"
        if exc.error_code == "payment_provider_unavailable":
            text_key = "payment_provider_unavailable"
        text = await texts.get(text_key)
        await safe_edit_or_answer(
            callback, text, reply_markup=back_kb(callback="profile")
        )
        await bot_log(
            api,
            level=LOG_LEVEL_WARNING,
            event="topup_create_client_error",
            user_id=user_id,
            message=exc.detail[:300],
            context={
                "error_code": exc.error_code,
                "provider": provider,
                "amount_kopecks": amount_kopecks,
            },
        )
        return
    except BackendUnavailableError as exc:
        await report_backend_unavailable(
            callback, api=api, texts=texts, user_id=user_id,
            error=exc, event="topup_create_backend_unavailable",
        )
        return
    except Exception as exc:  # noqa: BLE001
        await report_unexpected(
            callback, api=api, texts=texts, user_id=user_id,
            error=exc, event="topup_create_unexpected",
        )
        return

    payment_url = str(result.get("payment_url", ""))
    payment_id = result.get("payment_id")
    if not payment_url:
        await report_unexpected(
            callback,
            api=api, texts=texts, user_id=user_id,
            error=RuntimeError("backend returned no payment_url"),
            event="topup_create_missing_url",
            context={"provider": provider},
        )
        return

    text = await texts.get(
        "payment_invoice",
        amount=amount_kopecks // 100,
        payment_id=payment_id or "",
        provider=provider,
    )
    await safe_edit_or_answer(
        callback, text, reply_markup=await payment_link_kb(payment_url, text_service=texts)
    )

    # Top-up doesn't have an "awaiting" FSM — clear and let the worker take
    # over after webhook arrives.
    await state.clear()

    await bot_log(
        api,
        level=LOG_LEVEL_INFO,
        event="topup_invoice_sent",
        user_id=user_id,
        message="Top-up invoice URL delivered to user",
        context={
            "tg_id": tg_id,
            "provider": provider,
            "payment_id": payment_id,
            "amount_kopecks": amount_kopecks,
        },
    )
