"""Catalog flow: list tariffs → pick tariff → pick duration → enter promo.

Stage 2 details:
- Clicking the FREE tariff issues a 3-day key inline (same flow as a paid
  purchase final state, but synchronous and bypassing payment).
- Picking a paid tariff stores ``tariff_id`` in FSM and shows duration list.
- Picking a duration stores ``duration_id`` and enters
  :pyattr:`PurchaseStates.promo_input` — Stage 3 will read promo codes from
  free-text messages here.
- The "Нет промокода" button advances to :pyattr:`PurchaseStates.payment_method`.
"""

from __future__ import annotations

from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.api_client import BackendClient
from app.config import Settings
from app.handlers._common import (
    report_backend_unavailable,
    report_unexpected,
    safe_edit_or_answer,
    safe_edit_or_send_media,
)
from app.keyboards.catalog import (
    apply_discount,
    catalog_kb,
    key_issued_kb,
    payment_methods_kb,
    promo_retry_kb,
    promo_skip_kb,
    tariff_durations_kb,
)
from app.keyboards.common import back_kb
from app.states.purchase import PurchaseStates
from app.utils.errors import BackendClientError, BackendUnavailableError
from app.utils.logging import LOG_LEVEL_INFO, bot_log, get_logger
from app.utils.texts import TextService

router = Router(name="catalog")
log = get_logger("bot.handlers.catalog")


# ---- helpers ---------------------------------------------------------------


def _find_tariff(tariffs: list[dict[str, Any]], tariff_id: int) -> dict[str, Any] | None:
    for t in tariffs:
        if int(t.get("id", -1)) == tariff_id:
            return t
    return None


def _find_duration(
    tariff: dict[str, Any], duration_id: int
) -> dict[str, Any] | None:
    for d in tariff.get("durations") or []:
        if int(d.get("id", -1)) == duration_id:
            return d
    return None


# ---- catalog list ----------------------------------------------------------


@router.callback_query(F.data == "catalog")
async def cb_catalog(
    callback: CallbackQuery,
    api: BackendClient,
    texts: TextService,
    state: FSMContext,
    db_user: dict[str, Any] | None = None,
) -> None:
    """Show the tariff list (FREE first, then paid by sort_order)."""
    # Reset any in-flight purchase FSM data — opening the catalog is a fresh start.
    await state.clear()

    try:
        tariffs = await api.get_tariffs()
    except BackendUnavailableError as exc:
        await report_backend_unavailable(
            callback,
            api=api,
            texts=texts,
            user_id=(db_user or {}).get("id"),
            error=exc,
            event="catalog_open_failed",
        )
        return
    except Exception as exc:  # noqa: BLE001
        await report_unexpected(
            callback,
            api=api,
            texts=texts,
            user_id=(db_user or {}).get("id"),
            error=exc,
            event="catalog_open_failed",
        )
        return

    entry = await texts.get_entry("catalog_header")
    await safe_edit_or_send_media(
        callback, entry, reply_markup=catalog_kb(tariffs)
    )


# ---- tariff pick -----------------------------------------------------------


@router.callback_query(F.data.startswith("tariff:"))
async def cb_tariff(
    callback: CallbackQuery,
    api: BackendClient,
    texts: TextService,
    state: FSMContext,
    settings: Settings,
    db_user: dict[str, Any] | None = None,
) -> None:
    """Branch by tariff kind: FREE → instant issue, paid → duration picker."""
    if callback.data is None or callback.from_user is None:
        await callback.answer()
        return

    try:
        tariff_id = int(callback.data.split(":", 1)[1])
    except (IndexError, ValueError):
        await callback.answer()
        return

    tg_id = callback.from_user.id
    user_id = (db_user or {}).get("id")

    try:
        tariffs = await api.get_tariffs()
    except BackendUnavailableError as exc:
        await report_backend_unavailable(
            callback, api=api, texts=texts, user_id=user_id,
            error=exc, event="tariff_open_failed",
        )
        return

    tariff = _find_tariff(tariffs, tariff_id)
    if tariff is None:
        await callback.answer("Тариф не найден", show_alert=True)
        return

    # ---- FREE-trial path ----
    if tariff.get("is_free_trial"):
        await _handle_free_trial(
            callback,
            api=api,
            texts=texts,
            settings=settings,
            tg_id=tg_id,
            user_id=user_id,
        )
        return

    # ---- Paid path: store tariff_id, show duration list ----
    await state.update_data(tariff_id=tariff_id)
    # NB: backend's ``tariff_durations_header`` template uses
    # ``{tariff_description}`` (see backend/app/seeds.py); the field on the
    # API response is ``description_html``. Keep both in sync here.
    entry = await texts.get_entry(
        "tariff_durations_header",
        tariff_name=tariff.get("name", ""),
        tariff_description=tariff.get("description_html") or "",
    )
    durations = tariff.get("durations") or []
    await safe_edit_or_send_media(
        callback, entry, reply_markup=tariff_durations_kb(tariff_id, durations)
    )


async def _handle_free_trial(
    callback: CallbackQuery,
    *,
    api: BackendClient,
    texts: TextService,
    settings: Settings,
    tg_id: int,
    user_id: int | None,
) -> None:
    """Activate the FREE trial and send the key inline.

    Backend errors of interest:
    - ``free_trial_already_used`` → friendly explanation + back.
    - ``vpn_provider_unavailable`` → "try later" + back.
    """
    try:
        result = await api.activate_free_trial(tg_id)
    except BackendClientError as exc:
        text_key, log_event = "unexpected_error", "free_trial_failed"
        if exc.error_code == "free_trial_already_used":
            text_key = "free_trial_already_used"
            log_event = "free_trial_already_used"
        elif exc.error_code == "vpn_provider_unavailable":
            text_key = "vpn_provider_unavailable"
            log_event = "vpn_provider_unavailable"
        text = await texts.get(text_key)
        await safe_edit_or_answer(
            callback, text, reply_markup=back_kb(callback="catalog")
        )
        await bot_log(
            api,
            level=LOG_LEVEL_INFO,
            event=log_event,
            user_id=user_id,
            message=exc.detail[:300],
            context={"error_code": exc.error_code, "tg_id": tg_id},
        )
        return
    except BackendUnavailableError as exc:
        await report_backend_unavailable(
            callback,
            api=api,
            texts=texts,
            user_id=user_id,
            error=exc,
            event="free_trial_backend_unavailable",
        )
        return
    except Exception as exc:  # noqa: BLE001
        await report_unexpected(
            callback, api=api, texts=texts, user_id=user_id,
            error=exc, event="free_trial_unexpected",
        )
        return

    entry = await texts.get_entry(
        "key_issued_free_trial",
        key_url=result.get("key_url", ""),
        days=result.get("days", 3),
        devices=result.get("devices", 3),
        subscription_id=result.get("subscription_id", ""),
    )
    await safe_edit_or_send_media(
        callback,
        entry,
        reply_markup=await key_issued_kb(
            settings.HOWTO_CONNECT_URL, text_service=texts
        ),
    )
    await bot_log(
        api,
        level=LOG_LEVEL_INFO,
        event="free_trial_issued",
        user_id=user_id,
        message="Free trial issued",
        context={
            "tg_id": tg_id,
            "subscription_id": result.get("subscription_id"),
        },
    )


# ---- duration pick → promo prompt ------------------------------------------


@router.callback_query(F.data.startswith("duration:"))
async def cb_duration(
    callback: CallbackQuery,
    texts: TextService,
    state: FSMContext,
) -> None:
    """Save ``duration_id`` to FSM and show the promo prompt."""
    if callback.data is None:
        await callback.answer()
        return

    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer()
        return
    try:
        tariff_id = int(parts[1])
        duration_id = int(parts[2])
    except ValueError:
        await callback.answer()
        return

    await state.update_data(tariff_id=tariff_id, duration_id=duration_id)
    await state.set_state(PurchaseStates.promo_input)

    entry = await texts.get_entry("promo_input_prompt")
    await safe_edit_or_send_media(callback, entry, reply_markup=promo_skip_kb())


_PROMO_CODE_MIN = 1
_PROMO_CODE_MAX = 64


@router.message(PurchaseStates.promo_input)
async def msg_promo_input(
    message: Message,
    api: BackendClient,
    texts: TextService,
    state: FSMContext,
    db_user: dict[str, Any] | None = None,
) -> None:
    """Validate + apply a typed promo code.

    Branches:
    - ``balance`` promo → backend has already credited the balance; we show
      a confirmation and bounce to the main menu (FSM cleared).
    - ``discount_percent`` promo → store ``promo_id``/``promo_percent`` in
      FSM, recompute the discounted price for the payment-method picker,
      transition to :pyattr:`PurchaseStates.payment_method`.
    - 4xx (``promo_not_found`` / ``promo_unavailable``) → keep state, swap
      the keyboard to "Ввести другой / Без промокода".
    - 5xx / network → service_unavailable + back to main menu.
    """
    if message.from_user is None:
        return

    code = (message.text or "").strip()
    user_id = (db_user or {}).get("id")
    tg_id = message.from_user.id

    # Length guard — backend will also reject, but we save a round-trip.
    if not (_PROMO_CODE_MIN <= len(code) <= _PROMO_CODE_MAX):
        text = await texts.get("promo_not_found")
        await message.answer(text, reply_markup=promo_retry_kb())
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
                "promo_unavailable"
                if exc.error_code != "promo_not_found"
                else "promo_not_found"
            )
            text = await texts.get(key)
            await message.answer(text, reply_markup=promo_retry_kb())
            await bot_log(
                api,
                level=LOG_LEVEL_INFO,
                event="promo_apply_rejected",
                user_id=user_id,
                message=exc.detail[:300],
                context={"error_code": exc.error_code, "tg_id": tg_id},
            )
            return
        # Unknown 4xx — surface as unexpected.
        await report_unexpected(
            message, api=api, texts=texts, user_id=user_id,
            error=exc, event="promo_apply_client_error",
        )
        return
    except BackendUnavailableError as exc:
        await report_backend_unavailable(
            message, api=api, texts=texts, user_id=user_id,
            error=exc, event="promo_apply_backend_unavailable",
        )
        return
    except Exception as exc:  # noqa: BLE001
        await report_unexpected(
            message, api=api, texts=texts, user_id=user_id,
            error=exc, event="promo_apply_unexpected",
        )
        return

    promo_type = str(result.get("type", ""))

    if promo_type == "balance":
        amount_kop = int(result.get("amount_kopecks", 0) or 0)
        balance_kop = int(result.get("balance_kopecks", 0) or 0)
        entry = await texts.get_entry(
            "promo_balance_applied",
            amount=amount_kop // 100,
            balance=balance_kop // 100,
        )
        await safe_edit_or_send_media(
            message, entry, reply_markup=back_kb(callback="main_menu")
        )
        await state.clear()
        await bot_log(
            api,
            level=LOG_LEVEL_INFO,
            event="promo_balance_applied",
            user_id=user_id,
            message="Balance promo applied",
            context={
                "tg_id": tg_id,
                "amount_kopecks": amount_kop,
                "promo_id": result.get("promo_id"),
            },
        )
        return

    if promo_type == "discount_percent":
        percent = int(result.get("percent", 0) or 0)
        promo_id_raw = result.get("promo_id")
        promo_id = int(promo_id_raw) if promo_id_raw is not None else None

        # Pull tariff/duration to compute the discounted preview if backend
        # didn't include it.
        data = await state.get_data()
        tariff_id_raw = data.get("tariff_id")
        duration_id_raw = data.get("duration_id")
        if tariff_id_raw is None or duration_id_raw is None:
            await message.answer(
                await texts.get("unexpected_error"),
                reply_markup=promo_retry_kb(),
            )
            return
        tariff_id = int(tariff_id_raw)
        duration_id = int(duration_id_raw)

        try:
            tariffs = await api.get_tariffs()
            balance_kop = await api.get_user_balance(tg_id)
        except BackendUnavailableError as exc:
            await report_backend_unavailable(
                message, api=api, texts=texts, user_id=user_id,
                error=exc, event="promo_apply_post_fetch_failed",
            )
            return

        tariff = _find_tariff(tariffs, tariff_id)
        duration = _find_duration(tariff or {}, duration_id) if tariff else None
        if tariff is None or duration is None:
            await cb_catalog_message(message, api, texts, state, db_user)
            return

        base_amount = int(duration.get("price_kopecks", 0))
        # Prefer backend-computed final amount; fall back to local recompute.
        final_amount_raw = result.get("final_amount_kopecks")
        if isinstance(final_amount_raw, int) and final_amount_raw > 0:
            final_amount = final_amount_raw
        else:
            final_amount = apply_discount(base_amount, percent)

        await state.update_data(
            tariff_id=tariff_id,
            duration_id=duration_id,
            amount_kopecks=base_amount,
            promo_id=promo_id,
            promo_percent=percent,
            final_amount_kopecks=final_amount,
        )
        await state.set_state(PurchaseStates.payment_method)

        entry = await texts.get_entry(
            "promo_discount_applied",
            percent=percent,
            amount=final_amount // 100,
        )
        await safe_edit_or_send_media(
            message,
            entry,
            reply_markup=await payment_methods_kb(
                base_amount,
                balance_kop,
                discount_percent=percent,
                text_service=texts,
            ),
        )
        await bot_log(
            api,
            level=LOG_LEVEL_INFO,
            event="promo_discount_applied",
            user_id=user_id,
            message="Discount promo applied",
            context={
                "tg_id": tg_id,
                "percent": percent,
                "promo_id": promo_id,
                "final_amount_kopecks": final_amount,
            },
        )
        return

    # Unknown promo type — treat as unexpected.
    await report_unexpected(
        message, api=api, texts=texts, user_id=user_id,
        error=RuntimeError(f"unknown promo type: {promo_type!r}"),
        event="promo_apply_unknown_type",
        context={"result": result},
    )


async def cb_catalog_message(
    message: Message,
    api: BackendClient,
    texts: TextService,
    state: FSMContext,
    db_user: dict[str, Any] | None = None,
) -> None:
    """Render the catalog list as a fresh message (used from message handlers).

    The CallbackQuery-based :func:`cb_catalog` cannot be called with a Message,
    so this is a thin parallel that just hits ``api.get_tariffs`` and replies.
    Used as a graceful fallback when FSM data is stale.
    """
    await state.clear()
    try:
        tariffs = await api.get_tariffs()
    except BackendUnavailableError as exc:
        await report_backend_unavailable(
            message, api=api, texts=texts,
            user_id=(db_user or {}).get("id"),
            error=exc, event="catalog_open_failed_fallback",
        )
        return

    entry = await texts.get_entry("catalog_header")
    await safe_edit_or_send_media(
        message, entry, reply_markup=catalog_kb(tariffs)
    )


@router.callback_query(F.data == "promo_retry", PurchaseStates.promo_input)
async def cb_promo_retry(
    callback: CallbackQuery,
    texts: TextService,
) -> None:
    """Re-show the promo prompt without leaving the state."""
    entry = await texts.get_entry("promo_input_prompt")
    await safe_edit_or_send_media(callback, entry, reply_markup=promo_skip_kb())


# ---- duration_back: re-render duration list (kept tariff_id in FSM) --------


@router.callback_query(F.data == "duration_back")
async def cb_duration_back(
    callback: CallbackQuery,
    api: BackendClient,
    texts: TextService,
    state: FSMContext,
    db_user: dict[str, Any] | None = None,
) -> None:
    """Go back from promo prompt to duration picker — reuse stored tariff_id."""
    data = await state.get_data()
    tariff_id_raw = data.get("tariff_id")
    if tariff_id_raw is None:
        # No FSM context — degrade to catalog.
        await cb_catalog(callback, api=api, texts=texts, state=state, db_user=db_user)
        return
    tariff_id = int(tariff_id_raw)

    # Reset the promo state but keep tariff_id.
    await state.set_state(state=None)
    await state.update_data(tariff_id=tariff_id)

    try:
        tariffs = await api.get_tariffs()
    except BackendUnavailableError as exc:
        await report_backend_unavailable(
            callback, api=api, texts=texts,
            user_id=(db_user or {}).get("id"),
            error=exc, event="duration_back_failed",
        )
        return

    tariff = _find_tariff(tariffs, tariff_id)
    if tariff is None:
        await cb_catalog(callback, api=api, texts=texts, state=state, db_user=db_user)
        return

    entry = await texts.get_entry(
        "tariff_durations_header",
        tariff_name=tariff.get("name", ""),
        tariff_description=tariff.get("description_html") or "",
    )
    durations = tariff.get("durations") or []
    await safe_edit_or_send_media(
        callback, entry, reply_markup=tariff_durations_kb(tariff_id, durations)
    )


# ---- promo_skip → payment-method picker ------------------------------------


@router.callback_query(F.data == "promo_skip", PurchaseStates.promo_input)
async def cb_promo_skip(
    callback: CallbackQuery,
    api: BackendClient,
    texts: TextService,
    state: FSMContext,
    db_user: dict[str, Any] | None = None,
) -> None:
    """Skip promo (Stage 2: it's the only option) and show payment methods."""
    if callback.from_user is None:
        await callback.answer()
        return

    tg_id = callback.from_user.id
    user_id = (db_user or {}).get("id")

    data = await state.get_data()
    tariff_id_raw = data.get("tariff_id")
    duration_id_raw = data.get("duration_id")
    if tariff_id_raw is None or duration_id_raw is None:
        # Stale FSM — bounce back to catalog.
        await cb_catalog(callback, api=api, texts=texts, state=state, db_user=db_user)
        return
    tariff_id = int(tariff_id_raw)
    duration_id = int(duration_id_raw)

    try:
        tariffs = await api.get_tariffs()
        balance = await api.get_user_balance(tg_id)
    except BackendUnavailableError as exc:
        await report_backend_unavailable(
            callback, api=api, texts=texts, user_id=user_id,
            error=exc, event="promo_skip_failed",
        )
        return
    except Exception as exc:  # noqa: BLE001
        await report_unexpected(
            callback, api=api, texts=texts, user_id=user_id,
            error=exc, event="promo_skip_unexpected",
        )
        return

    tariff = _find_tariff(tariffs, tariff_id)
    duration = _find_duration(tariff or {}, duration_id) if tariff else None
    if tariff is None or duration is None:
        await cb_catalog(callback, api=api, texts=texts, state=state, db_user=db_user)
        return

    amount = int(duration.get("price_kopecks", 0))
    await state.update_data(
        tariff_id=tariff_id,
        duration_id=duration_id,
        amount_kopecks=amount,
    )
    await state.set_state(PurchaseStates.payment_method)

    entry = await texts.get_entry(
        "pay_method_header",
        amount=amount // 100,
        balance=balance // 100,
        tariff_name=tariff.get("name", ""),
    )
    await safe_edit_or_send_media(
        callback,
        entry,
        reply_markup=await payment_methods_kb(amount, balance, text_service=texts),
    )
