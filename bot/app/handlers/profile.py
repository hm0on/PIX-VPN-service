"""Profile flow: balance + active subscriptions, subscription detail, extension.

Renders an HTML summary that includes the user's current balance (formatted
as whole rubles) and a list of active/pending subscriptions. Subscription
buttons navigate to per-subscription detail. The "Продлить" button (Stage 3)
opens an extension wizard that mirrors the purchase flow but stays scoped
to a single subscription.
"""

from __future__ import annotations

from datetime import datetime
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
)
from app.keyboards.catalog import (
    apply_discount,
    key_issued_kb,
    payment_link_kb,
    promo_retry_kb,
)
from app.keyboards.common import back_kb
from app.keyboards.profile import (
    extension_durations_kb,
    extension_payment_methods_kb,
    extension_promo_skip_kb,
    profile_kb,
    subscription_detail_kb,
)
from app.states.purchase import ExtendStates
from app.utils.errors import BackendClientError, BackendUnavailableError
from app.utils.logging import LOG_LEVEL_INFO, LOG_LEVEL_WARNING, bot_log, get_logger
from app.utils.texts import TextService

router = Router(name="profile")
log = get_logger("bot.handlers.profile")


_EXT_PROVIDERS: frozenset[str] = frozenset(
    {"platega_sbp", "platega_crypto", "cryptobot", "balance"}
)
_PROMO_CODE_MIN = 1
_PROMO_CODE_MAX = 64


def _format_date(value: Any) -> str:
    """Best-effort ``DD.MM.YYYY`` from ISO/epoch — mirrors profile keyboard."""
    if not value:
        return "—"
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return "—"
    elif isinstance(value, (int, float)):
        dt = datetime.fromtimestamp(value)
    else:
        return "—"
    return dt.strftime("%d.%m.%Y")


def _render_subs_summary(subs: list[dict[str, Any]]) -> str:
    """Compact <ul>-style HTML summary of active subscriptions for the profile.

    Returned as plain text lines joined by ``\n`` — caller wraps it into the
    text template.
    """
    lines: list[str] = []
    for sub in subs:
        if str(sub.get("status", "")) not in {"active", "pending"}:
            continue
        name = sub.get("tariff_name") or sub.get("name") or "Подписка"
        expires = _format_date(sub.get("expires_at"))
        lines.append(f"• <b>{name}</b> — до {expires}")
    return "\n".join(lines)


@router.callback_query(F.data == "profile")
async def cb_profile(
    callback: CallbackQuery,
    api: BackendClient,
    texts: TextService,
    state: FSMContext,
    db_user: dict[str, Any] | None = None,
) -> None:
    """Render the profile (balance + subscriptions list)."""
    if callback.from_user is None:
        await callback.answer()
        return

    # Profile is a dead-end — clear any unrelated FSM state.
    await state.clear()

    tg_id = callback.from_user.id
    user_id = (db_user or {}).get("id")

    try:
        balance = await api.get_user_balance(tg_id)
        subs = await api.get_user_subscriptions(tg_id)
    except BackendUnavailableError as exc:
        await report_backend_unavailable(
            callback, api=api, texts=texts, user_id=user_id,
            error=exc, event="profile_open_failed",
        )
        return
    except Exception as exc:  # noqa: BLE001
        await report_unexpected(
            callback, api=api, texts=texts, user_id=user_id,
            error=exc, event="profile_open_unexpected",
        )
        return

    active_subs = [s for s in subs if str(s.get("status", "")) in {"active", "pending"}]
    has_active = bool(active_subs)

    # Referral count: best-effort. The screen still works if backend is in
    # the middle of a hiccup — we just degrade to 0.
    invited_count = 0
    try:
        ref_stats = await api.get_referral_stats(tg_id)
        invited_count = int(ref_stats.get("invited", 0) or 0)
    except Exception as exc:  # noqa: BLE001
        # Best-effort: don't blow up the profile screen if the referral
        # endpoint is flaky. Covers BackendUnavailableError /
        # BackendClientError / unexpected runtime errors alike.
        log.warning("profile.referral_stats_failed", error=str(exc))

    # Pull display name from the bot user (UserMiddleware-attached) so we
    # don't make an extra round-trip — fall back to the Telegram object.
    db = db_user or {}
    first_name = (
        db.get("first_name")
        or (callback.from_user.first_name if callback.from_user else None)
        or ""
    )
    last_name = (
        db.get("last_name")
        or (callback.from_user.last_name if callback.from_user else None)
        or ""
    )
    full_name = (f"{first_name} {last_name}").strip() or "—"
    username = db.get("username") or (
        callback.from_user.username if callback.from_user else None
    )
    username_display = f"@{username}" if username else "—"

    fmt: dict[str, Any] = {
        "balance": balance // 100,
        "name": full_name,
        "username": username_display,
        "tg_id": tg_id,
        "subs_count": len(active_subs),
        "invited_count": invited_count,
    }
    if has_active:
        fmt["subscriptions"] = _render_subs_summary(active_subs)
        text = await texts.get("profile_header", **fmt)
    else:
        text = await texts.get("profile_no_subscriptions", **fmt)

    await safe_edit_or_answer(
        callback, text, reply_markup=profile_kb(active_subs, has_active)
    )


@router.callback_query(F.data.startswith("sub:"))
async def cb_subscription(
    callback: CallbackQuery,
    api: BackendClient,
    texts: TextService,
    settings: Settings,
    db_user: dict[str, Any] | None = None,
) -> None:
    """Show details of a single subscription owned by the current user."""
    if callback.data is None or callback.from_user is None:
        await callback.answer()
        return

    try:
        subscription_id = int(callback.data.split(":", 1)[1])
    except (IndexError, ValueError):
        await callback.answer()
        return

    tg_id = callback.from_user.id
    user_id = (db_user or {}).get("id")

    try:
        sub = await api.get_subscription_detail(subscription_id, tg_id)
    except BackendClientError as exc:
        if exc.status_code in (403, 404):
            await callback.answer("Подписка не найдена", show_alert=True)
            return
        await report_unexpected(
            callback, api=api, texts=texts, user_id=user_id,
            error=exc, event="subscription_detail_failed",
            context={"subscription_id": subscription_id},
        )
        return
    except BackendUnavailableError as exc:
        await report_backend_unavailable(
            callback, api=api, texts=texts, user_id=user_id,
            error=exc, event="subscription_detail_backend_unavailable",
        )
        return
    except Exception as exc:  # noqa: BLE001
        await report_unexpected(
            callback, api=api, texts=texts, user_id=user_id,
            error=exc, event="subscription_detail_unexpected",
        )
        return

    text = await texts.get(
        "subscription_detail",
        tariff_name=sub.get("tariff_name", "—"),
        devices=sub.get("devices", "—"),
        days=sub.get("days", "—"),
        started_at=_format_date(sub.get("started_at")),
        expires_at=_format_date(sub.get("expires_at")),
        key_url=sub.get("key_url", ""),
        status=sub.get("status", ""),
        subscription_id=subscription_id,
    )
    await safe_edit_or_answer(
        callback,
        text,
        reply_markup=subscription_detail_kb(
            subscription_id, howto_url=settings.HOWTO_CONNECT_URL
        ),
    )


# ---- extension flow --------------------------------------------------------


async def _fetch_extension_durations(
    *,
    api: BackendClient,
    sub: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return the list of durations for the tariff that owns ``sub``.

    The subscription detail payload includes ``tariff_id``; we look it up in
    the catalog so the user picks an extension only from the same tariff.
    """
    tariff_id_raw = sub.get("tariff_id")
    if tariff_id_raw is None:
        return []
    try:
        tariff_id = int(tariff_id_raw)
    except (TypeError, ValueError):
        return []

    tariffs = await api.get_tariffs()
    for t in tariffs:
        try:
            if int(t.get("id", -1)) == tariff_id:
                return [d for d in (t.get("durations") or []) if isinstance(d, dict)]
        except (TypeError, ValueError):
            continue
    return []


def _find_duration(
    durations: list[dict[str, Any]], duration_id: int
) -> dict[str, Any] | None:
    for d in durations:
        try:
            if int(d.get("id", -1)) == duration_id:
                return d
        except (TypeError, ValueError):
            continue
    return None


@router.callback_query(F.data.startswith("extend:"))
async def cb_extend(
    callback: CallbackQuery,
    api: BackendClient,
    texts: TextService,
    state: FSMContext,
    db_user: dict[str, Any] | None = None,
) -> None:
    """Open the extension wizard for ``sub_id``.

    Verifies the sub belongs to the user and is ``active`` (other statuses
    can't be extended). Then renders the duration picker scoped to the same
    tariff.
    """
    if callback.data is None or callback.from_user is None:
        await callback.answer()
        return

    try:
        subscription_id = int(callback.data.split(":", 1)[1])
    except (IndexError, ValueError):
        await callback.answer()
        return

    tg_id = callback.from_user.id
    user_id = (db_user or {}).get("id")

    try:
        sub = await api.get_subscription_detail(subscription_id, tg_id)
    except BackendClientError as exc:
        if exc.status_code in (403, 404):
            await callback.answer("Подписка не найдена", show_alert=True)
            return
        await report_unexpected(
            callback, api=api, texts=texts, user_id=user_id,
            error=exc, event="extend_open_client_error",
            context={"subscription_id": subscription_id},
        )
        return
    except BackendUnavailableError as exc:
        await report_backend_unavailable(
            callback, api=api, texts=texts, user_id=user_id,
            error=exc, event="extend_open_backend_unavailable",
        )
        return
    except Exception as exc:  # noqa: BLE001
        await report_unexpected(
            callback, api=api, texts=texts, user_id=user_id,
            error=exc, event="extend_open_unexpected",
        )
        return

    if str(sub.get("status", "")) != "active":
        text = await texts.get("subscription_not_extendable")
        await safe_edit_or_answer(
            callback, text, reply_markup=back_kb(callback="profile")
        )
        return

    try:
        durations = await _fetch_extension_durations(api=api, sub=sub)
    except BackendUnavailableError as exc:
        await report_backend_unavailable(
            callback, api=api, texts=texts, user_id=user_id,
            error=exc, event="extend_durations_backend_unavailable",
        )
        return

    if not durations:
        # Tariff has no purchasable durations any more (deactivated / FREE-only).
        text = await texts.get("subscription_not_extendable")
        await safe_edit_or_answer(
            callback, text, reply_markup=back_kb(callback="profile")
        )
        return

    # Reset any other in-flight FSM and prime extension data.
    await state.clear()
    await state.update_data(subscription_id=subscription_id)

    text = await texts.get("extension_select_duration")
    await safe_edit_or_answer(
        callback,
        text,
        reply_markup=extension_durations_kb(durations, subscription_id),
    )


@router.callback_query(F.data.startswith("ext_duration:"))
async def cb_ext_duration(
    callback: CallbackQuery,
    texts: TextService,
    state: FSMContext,
) -> None:
    """Save the chosen duration and prompt for a promo code."""
    if callback.data is None:
        await callback.answer()
        return

    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer()
        return
    try:
        subscription_id = int(parts[1])
        duration_id = int(parts[2])
    except ValueError:
        await callback.answer()
        return

    await state.update_data(
        subscription_id=subscription_id,
        duration_id=duration_id,
    )
    await state.set_state(ExtendStates.promo_input)

    text = await texts.get("promo_input_prompt")
    await safe_edit_or_answer(
        callback, text,
        reply_markup=extension_promo_skip_kb(subscription_id, duration_id),
    )


@router.message(ExtendStates.promo_input)
async def msg_ext_promo_input(
    message: Message,
    api: BackendClient,
    texts: TextService,
    state: FSMContext,
    db_user: dict[str, Any] | None = None,
) -> None:
    """Apply a promo within the extension flow.

    Mirrors the purchase-side promo handler but only stores ``promo_id`` in
    FSM (balance-type promos still credit the balance and roll the user back
    to the main menu — extension does not auto-continue from there).
    """
    if message.from_user is None:
        return

    code = (message.text or "").strip()
    user_id = (db_user or {}).get("id")
    tg_id = message.from_user.id

    data = await state.get_data()
    sub_id_raw = data.get("subscription_id")
    duration_id_raw = data.get("duration_id")
    if sub_id_raw is None or duration_id_raw is None:
        await state.clear()
        await message.answer(await texts.get("unexpected_error"))
        return
    subscription_id = int(sub_id_raw)
    duration_id = int(duration_id_raw)

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
            return
        await report_unexpected(
            message, api=api, texts=texts, user_id=user_id,
            error=exc, event="ext_promo_apply_client_error",
        )
        return
    except BackendUnavailableError as exc:
        await report_backend_unavailable(
            message, api=api, texts=texts, user_id=user_id,
            error=exc, event="ext_promo_apply_backend_unavailable",
        )
        return
    except Exception as exc:  # noqa: BLE001
        await report_unexpected(
            message, api=api, texts=texts, user_id=user_id,
            error=exc, event="ext_promo_apply_unexpected",
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
        return

    if promo_type == "discount_percent":
        promo_id_raw = result.get("promo_id")
        promo_id = int(promo_id_raw) if promo_id_raw is not None else None
        percent = int(result.get("percent", 0) or 0)

        await state.update_data(promo_id=promo_id, promo_percent=percent)
        await state.set_state(ExtendStates.payment_method)

        try:
            balance_kop = await api.get_user_balance(tg_id)
        except BackendUnavailableError as exc:
            await report_backend_unavailable(
                message, api=api, texts=texts, user_id=user_id,
                error=exc, event="ext_promo_post_balance_failed",
            )
            return

        # Resolve the duration price for the picker. We re-fetch the sub to
        # avoid stashing the price in FSM (it can change in the admin UI).
        try:
            sub = await api.get_subscription_detail(subscription_id, tg_id)
            durations = await _fetch_extension_durations(api=api, sub=sub)
        except BackendUnavailableError as exc:
            await report_backend_unavailable(
                message, api=api, texts=texts, user_id=user_id,
                error=exc, event="ext_promo_post_durations_failed",
            )
            return

        duration = _find_duration(durations, duration_id)
        if duration is None:
            await message.answer(await texts.get("unexpected_error"))
            return

        base_amount = int(duration.get("price_kopecks", 0))
        # ``apply_discount`` is the same helper the purchase flow uses, so the
        # math (and rounding) stays consistent between flows.
        final_amount = apply_discount(base_amount, percent)

        text = await texts.get(
            "promo_discount_applied",
            percent=percent,
            amount=final_amount // 100,
        )
        await message.answer(
            text,
            reply_markup=extension_payment_methods_kb(
                subscription_id, duration_id, final_amount, balance_kop
            ),
        )
        return

    await report_unexpected(
        message, api=api, texts=texts, user_id=user_id,
        error=RuntimeError(f"unknown promo type: {promo_type!r}"),
        event="ext_promo_apply_unknown_type",
    )


@router.callback_query(F.data.startswith("ext_promo_skip:"))
async def cb_ext_promo_skip(
    callback: CallbackQuery,
    api: BackendClient,
    texts: TextService,
    state: FSMContext,
    db_user: dict[str, Any] | None = None,
) -> None:
    """Skip the promo step — render the extension payment-method picker."""
    if callback.data is None or callback.from_user is None:
        await callback.answer()
        return

    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer()
        return
    try:
        subscription_id = int(parts[1])
        duration_id = int(parts[2])
    except ValueError:
        await callback.answer()
        return

    tg_id = callback.from_user.id
    user_id = (db_user or {}).get("id")

    try:
        sub = await api.get_subscription_detail(subscription_id, tg_id)
        durations = await _fetch_extension_durations(api=api, sub=sub)
        balance_kop = await api.get_user_balance(tg_id)
    except BackendUnavailableError as exc:
        await report_backend_unavailable(
            callback, api=api, texts=texts, user_id=user_id,
            error=exc, event="ext_promo_skip_backend_unavailable",
        )
        return
    except Exception as exc:  # noqa: BLE001
        await report_unexpected(
            callback, api=api, texts=texts, user_id=user_id,
            error=exc, event="ext_promo_skip_unexpected",
        )
        return

    duration = _find_duration(durations, duration_id)
    if duration is None:
        await safe_edit_or_answer(
            callback,
            await texts.get("unexpected_error"),
            reply_markup=back_kb(callback="profile"),
        )
        return

    amount = int(duration.get("price_kopecks", 0))

    await state.update_data(
        subscription_id=subscription_id,
        duration_id=duration_id,
        promo_id=None,
        promo_percent=None,
    )
    await state.set_state(ExtendStates.payment_method)

    text = await texts.get(
        "pay_method_header",
        amount=amount // 100,
        balance=balance_kop // 100,
        tariff_name=sub.get("tariff_name", ""),
    )
    await safe_edit_or_answer(
        callback,
        text,
        reply_markup=extension_payment_methods_kb(
            subscription_id, duration_id, amount, balance_kop
        ),
    )


@router.callback_query(F.data.startswith("ext_pay:"), ExtendStates.payment_method)
async def cb_ext_pay(
    callback: CallbackQuery,
    api: BackendClient,
    texts: TextService,
    state: FSMContext,
    settings: Settings,
    db_user: dict[str, Any] | None = None,
) -> None:
    """Create the extension invoice (or instant-extend via balance)."""
    if callback.data is None or callback.from_user is None:
        await callback.answer()
        return

    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer()
        return
    try:
        subscription_id = int(parts[1])
        duration_id = int(parts[2])
    except ValueError:
        await callback.answer()
        return
    provider = parts[3]
    if provider not in _EXT_PROVIDERS:
        await callback.answer()
        return

    tg_id = callback.from_user.id
    user_id = (db_user or {}).get("id")

    data = await state.get_data()
    promo_id_raw = data.get("promo_id")
    promo_id = int(promo_id_raw) if promo_id_raw is not None else None

    try:
        result = await api.start_extension(
            subscription_id,
            duration_id,
            provider,
            tg_id=tg_id,
            promo_id=promo_id,
        )
    except BackendClientError as exc:
        text_key = "unexpected_error"
        if exc.error_code == "subscription_not_extendable":
            text_key = "subscription_not_extendable"
        elif exc.error_code == "insufficient_balance":
            text_key = "insufficient_balance"
        elif exc.error_code == "payment_provider_unavailable":
            text_key = "payment_provider_unavailable"
        elif exc.error_code == "vpn_provider_unavailable_refunded":
            text_key = "extension_failed_refund"
        elif exc.error_code == "vpn_provider_unavailable":
            text_key = "vpn_provider_unavailable"

        fmt: dict[str, Any] = {}
        if text_key == "insufficient_balance":
            # Backend's InsufficientBalanceError carries
            # ``current_balance_kopecks`` in ``details``. Accept the legacy
            # ``balance_kopecks`` key as a fallback.
            balance_kop_raw = (
                exc.payload.get("current_balance_kopecks")
                or exc.payload.get("balance_kopecks")
                or 0
            )
            try:
                fmt = {"balance": int(balance_kop_raw) // 100}  # type: ignore[arg-type]
            except (TypeError, ValueError):
                fmt = {"balance": 0}

        text = await texts.get(text_key, **fmt)
        await safe_edit_or_answer(
            callback, text, reply_markup=back_kb(callback="profile")
        )
        await bot_log(
            api,
            level=LOG_LEVEL_WARNING,
            event="extension_start_client_error",
            user_id=user_id,
            message=exc.detail[:300],
            context={
                "error_code": exc.error_code,
                "subscription_id": subscription_id,
                "duration_id": duration_id,
                "provider": provider,
            },
        )
        await state.clear()
        return
    except BackendUnavailableError as exc:
        await report_backend_unavailable(
            callback, api=api, texts=texts, user_id=user_id,
            error=exc, event="extension_start_backend_unavailable",
        )
        return
    except Exception as exc:  # noqa: BLE001
        await report_unexpected(
            callback, api=api, texts=texts, user_id=user_id,
            error=exc, event="extension_start_unexpected",
        )
        return

    # Branch: balance provider returns the new key/expires_at synchronously;
    # external providers return a payment_url and the worker delivers the
    # confirmation later.
    key_url = str(result.get("key_url", "") or "")
    new_expires_at = result.get("new_expires_at") or result.get("expires_at") or "—"
    payment_url = str(result.get("payment_url", "") or "")
    payment_id = result.get("payment_id")

    if provider == "balance" and (key_url or new_expires_at != "—"):
        text = await texts.get(
            "subscription_extended", new_expires_at=_format_date(new_expires_at)
        )
        await safe_edit_or_answer(
            callback, text, reply_markup=key_issued_kb(settings.HOWTO_CONNECT_URL)
        )
        await state.clear()
        await bot_log(
            api,
            level=LOG_LEVEL_INFO,
            event="extension_balance_success",
            user_id=user_id,
            message="Extension paid from balance",
            context={
                "subscription_id": subscription_id,
                "duration_id": duration_id,
                "payment_id": payment_id,
            },
        )
        return

    if not payment_url:
        await report_unexpected(
            callback, api=api, texts=texts, user_id=user_id,
            error=RuntimeError("backend returned no payment_url for extension"),
            event="extension_start_missing_url",
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
    await state.set_state(ExtendStates.awaiting_payment)

    await bot_log(
        api,
        level=LOG_LEVEL_INFO,
        event="extension_invoice_sent",
        user_id=user_id,
        message="Extension invoice URL delivered to user",
        context={
            "subscription_id": subscription_id,
            "duration_id": duration_id,
            "provider": provider,
            "payment_id": payment_id,
        },
    )


@router.callback_query(F.data.startswith("sub_howto:"))
async def cb_sub_howto(
    callback: CallbackQuery, texts: TextService, settings: Settings
) -> None:
    """Fallback "Как подключиться" — used when no HOWTO_CONNECT_URL is set.

    If the URL is set, the keyboard already has a direct link button and this
    handler isn't triggered.
    """
    if settings.HOWTO_CONNECT_URL:
        # Keyboard should already have used the URL variant; if we get here
        # anyway just answer the callback silently.
        await callback.answer()
        return

    text = await texts.get("howto_connect_fallback")
    await safe_edit_or_answer(
        callback, text, reply_markup=back_kb(callback="profile")
    )
