"""Standalone promo-code flow reachable from the main-menu "Промокод" button.

The catalog flow already knows how to apply promos — but only as part of a
purchase (``PurchaseStates.promo_input``). When the user clicks "Промокод"
in the main menu they want to redeem a *balance* promo without any
in-flight purchase. Discount promos here are politely rejected with a hint
to start a purchase first, since there's no tariff/duration to attach the
discount to.

Backend's ``apply_promo`` is safe to call standalone — see
``backend/app/services/promo_service.py``: balance promos credit the user
immediately and write a ``PromoActivation`` with ``payment_id=None``;
discount promos return metadata only (no side-effects).
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
from app.keyboards.common import back_kb
from app.states.purchase import PromoStates
from app.utils.errors import BackendClientError, BackendUnavailableError
from app.utils.logging import LOG_LEVEL_INFO, bot_log, get_logger
from app.utils.texts import TextService

router = Router(name="promo")
log = get_logger("bot.handlers.promo")


_PROMO_CODE_MIN = 1
_PROMO_CODE_MAX = 64


@router.callback_query(F.data == "promo")
async def cb_promo_open(
    callback: CallbackQuery,
    texts: TextService,
    state: FSMContext,
) -> None:
    """Enter ``PromoStates.input`` and prompt for a code.

    We `state.clear()` first because the user might be mid-purchase or
    have stale data — a standalone promo entry is a fresh start.
    """
    await state.clear()
    await state.set_state(PromoStates.input)
    text = await texts.get("promo_input_prompt")
    await safe_edit_or_answer(
        callback, text, reply_markup=back_kb(callback="main_menu")
    )


@router.message(PromoStates.input)
async def msg_promo_apply(
    message: Message,
    api: BackendClient,
    texts: TextService,
    state: FSMContext,
    db_user: dict[str, Any] | None = None,
) -> None:
    """Validate + apply a typed promo code from the standalone flow.

    Only ``balance`` promos complete here — they self-credit and we drop
    the user back to the main menu. ``discount_percent`` promos require an
    in-flight purchase and are rejected with a helpful hint.
    """
    if message.from_user is None:
        return

    code = (message.text or "").strip()
    user_id = (db_user or {}).get("id")
    tg_id = message.from_user.id

    # Length guard mirrors the catalog handler.
    if not (_PROMO_CODE_MIN <= len(code) <= _PROMO_CODE_MAX):
        text = await texts.get("promo_not_found")
        await message.answer(text, reply_markup=back_kb(callback="main_menu"))
        return

    try:
        result = await api.apply_promo(tg_id=tg_id, code=code)
    except BackendClientError as exc:
        if exc.error_code in {
            "promo_not_found",
            "promo_unavailable",
            "promo_max_per_user_reached",
            "promo_max_total_reached",
        }:
            key = (
                "promo_not_found"
                if exc.error_code == "promo_not_found"
                else "promo_unavailable"
            )
            text = await texts.get(key)
            await message.answer(text, reply_markup=back_kb(callback="main_menu"))
            await state.clear()
            await bot_log(
                api,
                level=LOG_LEVEL_INFO,
                event="promo_standalone_rejected",
                user_id=user_id,
                message=exc.detail[:300],
                context={"error_code": exc.error_code, "tg_id": tg_id},
            )
            return
        # Unknown 4xx — surface as unexpected.
        await report_unexpected(
            message, api=api, texts=texts, user_id=user_id,
            error=exc, event="promo_standalone_client_error",
        )
        return
    except BackendUnavailableError as exc:
        await report_backend_unavailable(
            message, api=api, texts=texts, user_id=user_id,
            error=exc, event="promo_standalone_backend_unavailable",
        )
        return
    except Exception as exc:  # noqa: BLE001
        await report_unexpected(
            message, api=api, texts=texts, user_id=user_id,
            error=exc, event="promo_standalone_unexpected",
        )
        return

    promo_type = str(result.get("type", ""))

    if promo_type == "balance":
        amount_kop = int(result.get("amount_kopecks", 0) or 0)
        balance_kop = int(result.get("balance_kopecks", 0) or 0)
        text = await texts.get(
            "promo_balance_applied",
            amount=amount_kop // 100,
            balance=balance_kop // 100,
        )
        await message.answer(text, reply_markup=back_kb(callback="main_menu"))
        await state.clear()
        await bot_log(
            api,
            level=LOG_LEVEL_INFO,
            event="promo_balance_applied",
            user_id=user_id,
            message="Balance promo applied (standalone)",
            context={
                "tg_id": tg_id,
                "amount_kopecks": amount_kop,
                "promo_id": result.get("promo_id"),
            },
        )
        return

    if promo_type == "discount_percent":
        # Discount promos are useless without a purchase — explain and
        # leave the user at the main menu so they can pick a tariff.
        text = await texts.get("promo_discount_requires_purchase")
        await message.answer(text, reply_markup=back_kb(callback="main_menu"))
        await state.clear()
        await bot_log(
            api,
            level=LOG_LEVEL_INFO,
            event="promo_discount_standalone_rejected",
            user_id=user_id,
            message="Discount promo entered outside a purchase",
            context={"tg_id": tg_id, "code": code[:64]},
        )
        return

    # Unknown promo type — bail to the generic unexpected path.
    await report_unexpected(
        message, api=api, texts=texts, user_id=user_id,
        error=RuntimeError(f"unknown promo type: {promo_type!r}"),
        event="promo_standalone_unknown_type",
        context={"result": result},
    )
