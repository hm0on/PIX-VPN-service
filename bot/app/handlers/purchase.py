"""Purchase finalisation: payment-method picker and post-pay state.

The catalog handler brings the user up to ``PurchaseStates.payment_method``
with ``tariff_id``, ``duration_id``, ``amount_kopecks`` already in FSM. From
here we:

1. ``pay:balance``  → call ``purchase_with_balance`` and immediately render
   the issued key (synchronous flow).
2. ``pay:{provider}`` for an external provider → call ``start_purchase``,
   show the "Оплатить" button. The webhook → outbox → worker pipeline
   delivers the key message later; the bot itself does *not* poll.
3. ``pay_cancel`` → drop FSM, back to catalog.
4. ``pay_back``   → re-render duration list (uses logic in catalog.py).
"""

from __future__ import annotations

from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from app.api_client import BackendClient
from app.config import Settings
from app.handlers._common import (
    report_backend_unavailable,
    report_unexpected,
    safe_edit_or_answer,
)
from app.keyboards.catalog import (
    key_issued_kb,
    payment_link_kb,
)
from app.keyboards.common import back_kb
from app.states.purchase import PurchaseStates
from app.utils.errors import BackendClientError, BackendUnavailableError
from app.utils.logging import LOG_LEVEL_INFO, LOG_LEVEL_WARNING, bot_log, get_logger
from app.utils.texts import TextService

router = Router(name="purchase")
log = get_logger("bot.handlers.purchase")


_PROVIDERS: frozenset[str] = frozenset(
    {"platega_sbp", "platega_crypto", "cryptobot", "balance"}
)


@router.callback_query(F.data.startswith("pay:"), PurchaseStates.payment_method)
async def cb_pay(
    callback: CallbackQuery,
    api: BackendClient,
    texts: TextService,
    state: FSMContext,
    settings: Settings,
    db_user: dict[str, Any] | None = None,
) -> None:
    """Dispatch by provider chosen by the user."""
    if callback.data is None or callback.from_user is None:
        await callback.answer()
        return

    provider = callback.data.split(":", 1)[1] if ":" in callback.data else ""
    if provider not in _PROVIDERS:
        await callback.answer()
        return

    tg_id = callback.from_user.id
    user_id = (db_user or {}).get("id")

    data = await state.get_data()
    tariff_id_raw = data.get("tariff_id")
    duration_id_raw = data.get("duration_id")
    if tariff_id_raw is None or duration_id_raw is None:
        await callback.answer("Сессия истекла, начните заново", show_alert=True)
        await state.clear()
        return
    tariff_id = int(tariff_id_raw)
    duration_id = int(duration_id_raw)

    # Stage 3: optional discount-promo id stored by ``catalog.msg_promo_input``.
    promo_id_raw = data.get("promo_id")
    promo_id: int | None
    try:
        promo_id = int(promo_id_raw) if promo_id_raw is not None else None
    except (TypeError, ValueError):
        promo_id = None

    if provider == "balance":
        await _pay_with_balance(
            callback,
            api=api, texts=texts, state=state, settings=settings,
            tg_id=tg_id, user_id=user_id,
            tariff_id=tariff_id, duration_id=duration_id,
            promo_id=promo_id,
        )
        return

    await _pay_with_provider(
        callback,
        api=api, texts=texts, state=state,
        tg_id=tg_id, user_id=user_id,
        tariff_id=tariff_id, duration_id=duration_id,
        provider=provider,
        promo_id=promo_id,
    )


async def _pay_with_balance(
    callback: CallbackQuery,
    *,
    api: BackendClient,
    texts: TextService,
    state: FSMContext,
    settings: Settings,
    tg_id: int,
    user_id: int | None,
    tariff_id: int,
    duration_id: int,
    promo_id: int | None = None,
) -> None:
    """Synchronous balance-paid purchase. On success the key is rendered now."""
    try:
        result = await api.purchase_with_balance(
            tg_id, tariff_id, duration_id, promo_id=promo_id
        )
    except BackendClientError as exc:
        await _handle_purchase_client_error(
            callback,
            api=api, texts=texts, user_id=user_id, tg_id=tg_id, exc=exc,
        )
        return
    except BackendUnavailableError as exc:
        await report_backend_unavailable(
            callback, api=api, texts=texts, user_id=user_id,
            error=exc, event="purchase_balance_backend_unavailable",
        )
        return
    except Exception as exc:  # noqa: BLE001
        await report_unexpected(
            callback, api=api, texts=texts, user_id=user_id,
            error=exc, event="purchase_balance_unexpected",
        )
        return

    text = await texts.get(
        "key_issued",
        key_url=result.get("key_url", ""),
        payment_id=result.get("payment_id", ""),
        subscription_id=result.get("subscription_id", ""),
        amount=int(result.get("amount_kopecks", 0)) // 100,
    )
    await safe_edit_or_answer(
        callback, text, reply_markup=key_issued_kb(settings.HOWTO_CONNECT_URL)
    )
    await state.clear()
    await bot_log(
        api,
        level=LOG_LEVEL_INFO,
        event="purchase_balance_success",
        user_id=user_id,
        message="Subscription paid from balance",
        context={
            "tg_id": tg_id,
            "subscription_id": result.get("subscription_id"),
            "payment_id": result.get("payment_id"),
        },
    )


async def _handle_purchase_client_error(
    callback: CallbackQuery,
    *,
    api: BackendClient,
    texts: TextService,
    user_id: int | None,
    tg_id: int,
    exc: BackendClientError,
) -> None:
    """Map known balance-purchase error codes to user-friendly texts."""
    code = exc.error_code or ""
    text_key = "unexpected_error"
    log_level = LOG_LEVEL_WARNING
    fmt: dict[str, Any] = {}

    if code == "insufficient_balance":
        text_key = "insufficient_balance"
        # Backend's InsufficientBalanceError serialises ``details`` as
        # ``{"current_balance_kopecks": ..., "required_kopecks": ...}``;
        # ``api_client._request`` lifts those keys to ``payload``. Accept the
        # legacy ``balance_kopecks`` key too in case some callers still use it.
        balance_kop_raw = (
            exc.payload.get("current_balance_kopecks")
            or exc.payload.get("balance_kopecks")
            or 0
        )
        try:
            balance_kop = int(balance_kop_raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            balance_kop = 0
        fmt = {"balance": balance_kop // 100}
    elif code == "vpn_provider_unavailable_refunded":
        text_key = "refund_after_provider_error"
    elif code == "vpn_provider_unavailable":
        text_key = "vpn_provider_unavailable"
    else:
        log_level = LOG_LEVEL_WARNING

    text = await texts.get(text_key, **fmt)
    await safe_edit_or_answer(
        callback, text, reply_markup=back_kb(callback="catalog")
    )
    await bot_log(
        api,
        level=log_level,
        event="purchase_balance_client_error",
        user_id=user_id,
        message=exc.detail[:300],
        context={"error_code": code, "tg_id": tg_id},
    )


async def _pay_with_provider(
    callback: CallbackQuery,
    *,
    api: BackendClient,
    texts: TextService,
    state: FSMContext,
    tg_id: int,
    user_id: int | None,
    tariff_id: int,
    duration_id: int,
    provider: str,
    promo_id: int | None = None,
) -> None:
    """External provider flow: create invoice, show payment URL, wait."""
    try:
        result = await api.start_purchase(
            tg_id, tariff_id, duration_id, provider, promo_id=promo_id
        )
    except BackendClientError as exc:
        text_key = "unexpected_error"
        if exc.error_code == "payment_provider_unavailable":
            text_key = "payment_provider_unavailable"
        text = await texts.get(text_key)
        await safe_edit_or_answer(
            callback, text, reply_markup=back_kb(callback="catalog")
        )
        await bot_log(
            api,
            level=LOG_LEVEL_WARNING,
            event="purchase_start_client_error",
            user_id=user_id,
            message=exc.detail[:300],
            context={
                "error_code": exc.error_code,
                "provider": provider,
                "tg_id": tg_id,
            },
        )
        return
    except BackendUnavailableError as exc:
        await report_backend_unavailable(
            callback, api=api, texts=texts, user_id=user_id,
            error=exc, event="purchase_start_backend_unavailable",
        )
        return
    except Exception as exc:  # noqa: BLE001
        await report_unexpected(
            callback, api=api, texts=texts, user_id=user_id,
            error=exc, event="purchase_start_unexpected",
        )
        return

    payment_url = str(result.get("payment_url", ""))
    payment_id = result.get("payment_id")
    if not payment_url:
        await report_unexpected(
            callback,
            api=api, texts=texts, user_id=user_id,
            error=RuntimeError("backend returned no payment_url"),
            event="purchase_start_missing_url",
            context={"provider": provider},
        )
        return

    text = await texts.get(
        "payment_invoice",
        amount=int(result.get("amount_kopecks", 0)) // 100,
        payment_id=payment_id or "",
        provider=provider,
    )
    await safe_edit_or_answer(
        callback, text, reply_markup=payment_link_kb(payment_url)
    )

    await state.update_data(payment_id=payment_id, provider=provider)
    await state.set_state(PurchaseStates.awaiting_payment)

    await bot_log(
        api,
        level=LOG_LEVEL_INFO,
        event="purchase_invoice_sent",
        user_id=user_id,
        message="Invoice URL delivered to user",
        context={
            "tg_id": tg_id,
            "provider": provider,
            "payment_id": payment_id,
        },
    )


# ---- "Назад" / "Отменить" --------------------------------------------------


@router.callback_query(F.data == "pay_back")
async def cb_pay_back(
    callback: CallbackQuery,
    api: BackendClient,
    texts: TextService,
    state: FSMContext,
    db_user: dict[str, Any] | None = None,
) -> None:
    """Go back from payment-method picker to the duration picker.

    We delegate to ``catalog.cb_duration_back`` to avoid duplicating the
    "fetch tariffs + render durations" logic.
    """
    # Local import to avoid a circular import at module load time.
    from app.handlers.catalog import cb_duration_back

    await state.set_state(state=None)
    await cb_duration_back(callback, api=api, texts=texts, state=state, db_user=db_user)


@router.callback_query(F.data == "pay_cancel")
async def cb_pay_cancel(
    callback: CallbackQuery,
    api: BackendClient,
    texts: TextService,
    state: FSMContext,
    db_user: dict[str, Any] | None = None,
) -> None:
    """Cancel the in-flight invoice (Stage 2: bot-side only) and return to catalog."""
    # Local import to avoid a circular import at module load time.
    from app.handlers.catalog import cb_catalog

    await state.clear()
    await cb_catalog(callback, api=api, texts=texts, state=state, db_user=db_user)
