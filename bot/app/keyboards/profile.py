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
from app.utils.texts import TextService
from app.utils.texts import TextService


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


async def profile_kb(
    subscriptions: list[dict[str, Any]],
    has_active: bool,  # noqa: ARG001
    text_service: TextService,
) -> InlineKeyboardMarkup:
    """Profile keyboard — one button per active subscription, then actions.

    ``has_active`` is currently unused (we infer from the list length) but is
    kept in the signature for forward-compat with rich profile cards.
    Subscription rows still use a dynamically built label ("name, до date")
    so they're not seeded in the texts table — only the four navigation
    actions below are admin-editable.
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

    add_label, add_icon = await text_service.get_button("btn.profile.add_more")
    topup_label, topup_icon = await text_service.get_button("btn.profile.topup")
    ref_label, ref_icon = await text_service.get_button("btn.profile.referral")
    back_label, back_icon = await text_service.get_button("btn.common.back")
    rows.append(
        [
            make_button(
                add_label,
                callback_data="catalog",
                icon_custom_emoji_id=add_icon,
            )
        ]
    )
    rows.append(
        [
            make_button(
                topup_label,
                callback_data="topup",
                icon_custom_emoji_id=topup_icon,
            )
        ]
    )
    rows.append(
        [
            make_button(
                ref_label,
                callback_data="referral_program",
                icon_custom_emoji_id=ref_icon,
            )
        ]
    )
    rows.append(
        [
            make_button(
                back_label,
                callback_data="main_menu",
                icon_custom_emoji_id=back_icon,
            )
        ]
    )
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


async def subscription_detail_kb(
    subscription_id: int,
    howto_url: str | None = None,
    *,
    text_service: TextService,
) -> InlineKeyboardMarkup:
    """Subscription detail keyboard.

    "Как подключиться" prefers the configured ``howto_url`` (channel post);
    if none is set we fall back to a callback so the keyboard is still valid.
    """
    howto_label, howto_icon = await text_service.get_button("btn.subscription.howto")
    extend_label, extend_icon = await text_service.get_button(
        "btn.subscription.extend"
    )
    back_label, back_icon = await text_service.get_button("btn.common.back")

    rows: list[list[InlineKeyboardButton]] = []
    if howto_url:
        # External-link variant — Telegram doesn't allow icon_custom_emoji_id
        # on URL buttons in older clients, but the field is harmless in newer
        # ones, so we forward it the same way as callback buttons.
        rows.append(
            [
                make_button(
                    howto_label, url=howto_url, icon_custom_emoji_id=howto_icon
                )
            ]
        )
    else:
        rows.append(
            [
                make_button(
                    howto_label,
                    callback_data=f"sub_howto:{subscription_id}",
                    icon_custom_emoji_id=howto_icon,
                )
            ]
        )
    rows.append(
        [
            make_button(
                extend_label,
                callback_data=f"extend:{subscription_id}",
                icon_custom_emoji_id=extend_icon,
            )
        ]
    )
    rows.append(
        [
            make_button(
                back_label,
                callback_data="profile",
                icon_custom_emoji_id=back_icon,
            )
        ]
    )
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


async def topup_methods_kb(text_service: TextService) -> InlineKeyboardMarkup:
    """Top-up payment methods (no Balance — you're topping up the balance!)."""
    sbp_label, sbp_icon = await text_service.get_button("btn.payment.sbp")
    crypto_label, crypto_icon = await text_service.get_button("btn.payment.crypto")
    cb_label, cb_icon = await text_service.get_button("btn.payment.cryptobot")
    back_label, back_icon = await text_service.get_button("btn.common.back")
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                make_button(
                    sbp_label,
                    callback_data="topup_pay:platega_sbp",
                    color="blue",
                    icon_custom_emoji_id=sbp_icon,
                ),
                make_button(
                    cb_label,
                    callback_data="topup_pay:cryptobot",
                    color="blue",
                    icon_custom_emoji_id=cb_icon,
                ),
            ],
            [
                make_button(
                    crypto_label,
                    callback_data="topup_pay:platega_crypto",
                    color="blue",
                    icon_custom_emoji_id=crypto_icon,
                )
            ],
            [
                make_button(
                    back_label,
                    callback_data="profile",
                    icon_custom_emoji_id=back_icon,
                )
            ],
        ]
    )


async def topup_back_kb(text_service: TextService) -> InlineKeyboardMarkup:
    """Single back-to-profile button (used while the user types the amount)."""
    back_label, back_icon = await text_service.get_button("btn.common.back")
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                make_button(
                    back_label,
                    callback_data="profile",
                    icon_custom_emoji_id=back_icon,
                )
            ],
        ]
    )
