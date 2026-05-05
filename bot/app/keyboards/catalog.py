"""Inline keyboards for the catalog → duration → promo → payment flow.

All callbacks live in a single namespace so the dispatcher can route them
without ambiguity:

- ``catalog``                       — open the catalog list
- ``tariff:{id}``                   — pick a tariff
- ``duration:{tariff_id}:{dur_id}`` — pick a duration for a paid tariff
- ``promo_skip``                    — skip the (Stage-3) promo input
- ``duration_back``                 — go back to duration list (FSM keeps tariff_id)
- ``pay:{provider}``                — pick a payment method (purchase flow)
- ``pay_back``                      — go back from payment-method to duration
- ``pay_cancel``                    — cancel the invoice (returns to catalog)
- ``main_menu``                     — root navigation (handled by start.py)

Pricing is rendered in rubles (``price_kopecks // 100``) — no float math.
"""

from __future__ import annotations

from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.keyboards.main_menu import make_button


def _format_rub(amount_kopecks: int) -> str:
    """Format kopecks as `` ₽`` value with no fractional part.

    We always round *down* — UI shows whole rubles. Backend keeps kopecks
    for accuracy.
    """
    return f"{amount_kopecks // 100} ₽"


def _months_label(months: int) -> str:
    """Russian-pluralised "1 месяц / 3 месяца / 12 месяцев"."""
    if months % 10 == 1 and months % 100 != 11:
        word = "месяц"
    elif 2 <= months % 10 <= 4 and not 12 <= months % 100 <= 14:
        word = "месяца"
    else:
        word = "месяцев"
    return f"{months} {word}"


def _days_label(days: int) -> str:
    """Russian-pluralised "1 день / 3 дня / 14 дней"."""
    if days % 10 == 1 and days % 100 != 11:
        word = "день"
    elif 2 <= days % 10 <= 4 and not 12 <= days % 100 <= 14:
        word = "дня"
    else:
        word = "дней"
    return f"{days} {word}"


def _duration_label(days: int) -> str:
    """Friendly label for a duration expressed in days.

    Backend stores durations in *days* (30, 90, 180, 365, …). For typical
    monthly buckets we show "N месяцев"; for short or non-multiple values
    we fall back to "N дней" so we never show "0 месяцев".
    """
    if days <= 0:
        return _days_label(0)
    if days < 30:
        return _days_label(days)
    months = round(days / 30)
    return _months_label(max(1, months))


def catalog_kb(tariffs: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    """Render tariff list — FREE first, then paid tariffs by ``sort_order``.

    Tariffs lacking ``is_active=True`` are skipped. FREE is always pinned to
    the top regardless of its sort_order.
    """
    visible = [t for t in tariffs if t.get("is_active", True)]
    free = [t for t in visible if t.get("is_free_trial")]
    paid = [t for t in visible if not t.get("is_free_trial")]
    paid.sort(key=lambda t: int(t.get("sort_order", 0)))

    rows: list[list[InlineKeyboardButton]] = []
    for t in [*free, *paid]:
        label = str(t.get("name", "—"))
        # FREE: "FREE — 3 дня"; paid: "Basic — 3 устройства"
        if t.get("is_free_trial"):
            days = t.get("days")
            if days:
                label = f"{label} — {days} дня"
        else:
            devices = t.get("devices")
            if devices:
                label = f"{label} — {devices} устройств"
        rows.append([make_button(label, callback_data=f"tariff:{t['id']}")])

    rows.append([make_button("← Назад", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def tariff_durations_kb(
    tariff_id: int, durations: list[dict[str, Any]]
) -> InlineKeyboardMarkup:
    """Duration buttons for a paid tariff.

    ``durations`` items: ``{"id", "days", "price_kopecks", "is_hot"}``.
    Buttons are ordered by ``days`` ascending. The hot one gets a 🔥 suffix.
    Days are rendered as "N месяцев" (rounded) for the typical 30/90/180/365
    buckets and as "N дней" for short non-monthly durations.
    """
    sorted_durs = sorted(durations, key=lambda d: int(d.get("days", 0)))

    rows: list[list[InlineKeyboardButton]] = []
    for d in sorted_durs:
        days = int(d.get("days", 0))
        price = int(d.get("price_kopecks", 0))
        label = f"{_duration_label(days)} — {_format_rub(price)}"
        if d.get("is_hot"):
            label = f"{label} 🔥"
        rows.append(
            [
                make_button(
                    label, callback_data=f"duration:{tariff_id}:{d['id']}"
                )
            ]
        )

    rows.append([make_button("← Назад", callback_data="catalog")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def promo_skip_kb() -> InlineKeyboardMarkup:
    """Promo prompt keyboard.

    Initial state: user is invited to either type a code or skip. After a
    failed validation we swap to :func:`promo_retry_kb` instead of this one.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [make_button("Нет промокода", callback_data="promo_skip")],
            [make_button("← Назад", callback_data="duration_back")],
        ]
    )


def promo_retry_kb() -> InlineKeyboardMarkup:
    """Shown after a 4xx promo validation error.

    "Ввести другой" re-prompts the user (FSM stays in ``promo_input``).
    "Без промокода" delegates to the regular ``promo_skip`` callback.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [make_button("✏️ Ввести другой", callback_data="promo_retry")],
            [make_button("Без промокода", callback_data="promo_skip")],
            [make_button("← Назад", callback_data="duration_back")],
        ]
    )


def apply_discount(amount_kopecks: int, discount_percent: int | None) -> int:
    """Apply a percentage discount to a kopecks-denominated amount.

    Rounds *down* to the nearest kopeck (integer math) — the backend MUST do
    the same so the bot UI matches what's actually charged.
    Returns the original amount unchanged when ``discount_percent`` is falsy
    or out of the ``[0, 100]`` range.
    """
    if not discount_percent:
        return amount_kopecks
    pct = max(0, min(100, int(discount_percent)))
    return amount_kopecks * (100 - pct) // 100


def payment_methods_kb(
    amount_kopecks: int,
    balance_kopecks: int,
    *,
    discount_percent: int | None = None,
) -> InlineKeyboardMarkup:
    """4-button grid: SBP / CryptoBot / Crypto / Balance.

    The "Баланс" button is shown disabled-style (🔒 prefix) when the user
    can't afford the order — clicking it still goes through ``pay:balance``,
    where the handler explains *why* it failed instead of silently swallowing.

    ``discount_percent`` (Stage 3): when a discount-type promo is active for
    the in-flight purchase, recompute the effective amount so the balance
    affordability check uses the post-discount price.
    """
    effective_amount = apply_discount(amount_kopecks, discount_percent)
    can_use_balance = balance_kopecks >= effective_amount
    balance_label = "💰 Баланс" if can_use_balance else "🔒 Баланс"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                make_button("СБП", callback_data="pay:platega_sbp", color="blue"),
                make_button(
                    "CryptoBot", callback_data="pay:cryptobot", color="blue"
                ),
            ],
            [
                make_button(
                    "Криптовалюта",
                    callback_data="pay:platega_crypto",
                    color="blue",
                ),
                make_button(balance_label, callback_data="pay:balance"),
            ],
            [make_button("← Назад", callback_data="pay_back")],
        ]
    )


def payment_link_kb(payment_url: str) -> InlineKeyboardMarkup:
    """Final invoice keyboard: external pay button + cancel.

    "Оплатить" opens the provider page in the user's browser. "Отменить"
    just unwinds the FSM on our side — Stage 2 doesn't notify the provider.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить", url=payment_url)],
            [make_button("← Отменить", callback_data="pay_cancel")],
        ]
    )


def key_issued_kb(howto_url: str | None) -> InlineKeyboardMarkup:
    """Post-success keyboard shown to the user with the freshly issued key.

    "Как подключиться" is an external URL button (post in the channel) and
    is omitted gracefully if ``HOWTO_CONNECT_URL`` is unset — falling back
    to a callback that just shows a short hint via the about/help section.
    """
    rows: list[list[InlineKeyboardButton]] = []
    if howto_url:
        rows.append(
            [InlineKeyboardButton(text="📖 Как подключиться", url=howto_url)]
        )
    rows.append([make_button("🏠 В меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
