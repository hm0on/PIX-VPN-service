"""Inline keyboards for the profile / subscriptions / top-up / extension flow.

Callbacks:
- ``profile``                            — open profile (handled in profile.py)
- ``sub:{id}``                           — open subscription detail
- ``referral_program``                   — open referral screen (Stage 3)
- ``extend:{sub_id}``                    — open extension flow (Stage 3)
- ``ext_duration:{sub_id}:{dur_id}``     — pick extension duration
- ``ext_promo_skip:{sub_id}:{dur_id}``   — skip promo in extension flow
- ``ext_pay:{sub_id}:{dur_id}:{prov}``   — extension payment method
- ``ext_back:{sub_id}``                  — back from extension to sub detail
- ``topup``                              — start the top-up flow (FSM)
- ``topup_pay:{provider}``               — pick top-up payment method
- ``topup_back``                         — back from amount input to profile
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.keyboards.main_menu import make_button


def _format_short_date(value: Any) -> str:
    """Render an ISO-8601 string or epoch as ``DD.MM.YYYY``.

    Falls back to ``«—»`` if the value is missing/unparseable — keeps the
    button label readable when the backend returns nulls (e.g. pending sub).
    """
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


def profile_kb(
    subscriptions: list[dict[str, Any]], has_active: bool  # noqa: ARG001
) -> InlineKeyboardMarkup:
    """Profile keyboard — one button per active subscription, then actions.

    ``has_active`` is currently unused (we infer from the list length) but is
    kept in the signature for forward-compat with rich profile cards.
    """
    rows: list[list[InlineKeyboardButton]] = []

    for sub in subscriptions:
        status = str(sub.get("status", ""))
        if status not in {"active", "pending"}:
            continue
        name = sub.get("tariff_name") or sub.get("name") or "Подписка"
        expires = _format_short_date(sub.get("expires_at"))
        label = f"{name}, до {expires}"
        rows.append([make_button(label, callback_data=f"sub:{sub['id']}")])

    rows.append([make_button("➕ Оформить ещё", callback_data="catalog")])
    rows.append([make_button("💰 Пополнить баланс", callback_data="topup")])
    rows.append(
        [make_button("🎁 Реферальная программа", callback_data="referral_program")]
    )
    rows.append([make_button("← Назад", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def referral_kb(ref_link: str, share_text: str) -> InlineKeyboardMarkup:
    """Referral screen keyboard.

    "Поделиться" uses ``switch_inline_query`` so the user picks a chat and
    Telegram pre-fills the message with ``share_text`` (the ref link plus a
    short pitch). "← Назад" returns to the profile.
    """
    # ``ref_link`` is part of ``share_text`` already, kept as a parameter for
    # callers that want to log/inspect the link separately.
    _ = ref_link  # noqa: F841 — explicit "intentionally unused"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📤 Поделиться",
                    switch_inline_query=share_text,
                )
            ],
            [make_button("← Назад", callback_data="profile")],
        ]
    )


def subscription_detail_kb(
    subscription_id: int, howto_url: str | None = None  # noqa: ARG001
) -> InlineKeyboardMarkup:
    """Subscription detail keyboard.

    "Как подключиться" prefers the configured ``howto_url`` (channel post);
    if none is set we fall back to a callback so the keyboard is still valid.
    """
    rows: list[list[InlineKeyboardButton]] = []
    if howto_url:
        rows.append(
            [InlineKeyboardButton(text="📖 Как подключиться", url=howto_url)]
        )
    else:
        rows.append(
            [
                make_button(
                    "📖 Как подключиться",
                    callback_data=f"sub_howto:{subscription_id}",
                )
            ]
        )
    rows.append(
        [make_button("♻️ Продлить", callback_data=f"extend:{subscription_id}")]
    )
    rows.append([make_button("← Назад", callback_data="profile")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---- extension flow keyboards ---------------------------------------------


def _months_label(months: int) -> str:
    """Russian-pluralised "1 месяц / 3 месяца / 12 месяцев" — local copy.

    Duplicated from ``keyboards.catalog`` to avoid a cross-module import; it
    is a tiny pure helper.
    """
    if months % 10 == 1 and months % 100 != 11:
        word = "месяц"
    elif 2 <= months % 10 <= 4 and not 12 <= months % 100 <= 14:
        word = "месяца"
    else:
        word = "месяцев"
    return f"{months} {word}"


def _days_label(days: int) -> str:
    """Russian-pluralised "1 день / 3 дня / 14 дней" — local copy."""
    if days % 10 == 1 and days % 100 != 11:
        word = "день"
    elif 2 <= days % 10 <= 4 and not 12 <= days % 100 <= 14:
        word = "дня"
    else:
        word = "дней"
    return f"{days} {word}"


def _duration_label(days: int) -> str:
    """Friendly label for a duration expressed in days.

    Mirrors :func:`keyboards.catalog._duration_label` — see it for rationale.
    """
    if days <= 0:
        return _days_label(0)
    if days < 30:
        return _days_label(days)
    months = round(days / 30)
    return _months_label(max(1, months))


def extension_durations_kb(
    durations: list[dict[str, Any]], subscription_id: int
) -> InlineKeyboardMarkup:
    """Duration buttons for the extension flow.

    Mirrors :func:`keyboards.catalog.tariff_durations_kb` but routes to the
    extension namespace (``ext_duration``) and includes ``sub_id`` in every
    callback so the dispatcher doesn't depend on FSM for the sub identity.
    """
    sorted_durs = sorted(durations, key=lambda d: int(d.get("days", 0)))

    rows: list[list[InlineKeyboardButton]] = []
    for d in sorted_durs:
        days = int(d.get("days", 0))
        price_kop = int(d.get("price_kopecks", 0))
        label = f"{_duration_label(days)} — {price_kop // 100} ₽"
        if d.get("is_hot"):
            label = f"{label} 🔥"
        rows.append(
            [
                make_button(
                    label,
                    callback_data=f"ext_duration:{subscription_id}:{d['id']}",
                )
            ]
        )
    rows.append([make_button("← Назад", callback_data=f"sub:{subscription_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def extension_promo_skip_kb(
    subscription_id: int, duration_id: int
) -> InlineKeyboardMarkup:
    """Promo prompt for the extension flow."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                make_button(
                    "Нет промокода",
                    callback_data=f"ext_promo_skip:{subscription_id}:{duration_id}",
                )
            ],
            [make_button("← Назад", callback_data=f"extend:{subscription_id}")],
        ]
    )


def extension_payment_methods_kb(
    subscription_id: int,
    duration_id: int,
    amount_kopecks: int,
    balance_kopecks: int,
) -> InlineKeyboardMarkup:
    """Payment methods for the extension flow."""
    can_use_balance = balance_kopecks >= amount_kopecks
    balance_label = "💰 Баланс" if can_use_balance else "🔒 Баланс"
    base = f"ext_pay:{subscription_id}:{duration_id}"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                make_button("СБП", callback_data=f"{base}:platega_sbp"),
                make_button("CryptoBot", callback_data=f"{base}:cryptobot"),
            ],
            [
                make_button(
                    "Криптовалюта", callback_data=f"{base}:platega_crypto"
                ),
                make_button(balance_label, callback_data=f"{base}:balance"),
            ],
            [
                make_button(
                    "← Назад",
                    callback_data=f"ext_promo_skip:{subscription_id}:{duration_id}",
                )
            ],
        ]
    )


def topup_methods_kb() -> InlineKeyboardMarkup:
    """Top-up payment methods (no Balance — you're topping up the balance!)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                make_button(
                    "СБП", callback_data="topup_pay:platega_sbp", color="blue"
                ),
                make_button(
                    "CryptoBot", callback_data="topup_pay:cryptobot", color="blue"
                ),
            ],
            [
                make_button(
                    "Криптовалюта",
                    callback_data="topup_pay:platega_crypto",
                    color="blue",
                )
            ],
            [make_button("← Назад", callback_data="profile")],
        ]
    )


def topup_back_kb() -> InlineKeyboardMarkup:
    """Single back-to-profile button (used while the user types the amount)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [make_button("← Назад", callback_data="profile")],
        ]
    )
