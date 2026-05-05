"""Add kind + icon_custom_emoji_id to texts; seed button-label rows.

Stage 6 (admin button labels): the same ``texts`` table now stores both
message bodies (``kind='message'``, edited as rich HTML in TipTap) and
inline-button labels (``kind='button'``, edited as a plain string with an
optional ``icon_custom_emoji_id`` for premium emoji on the left of the
button). The two columns are nullable / defaulted so the migration is
backward-compatible — existing rows become ``kind='message'`` automatically.

The button rows are seeded here with the labels currently hardcoded in
``bot/app/keyboards/*.py`` so a fresh deploy renders the same UI even
before an admin opens the Texts editor. ``ON CONFLICT (key) DO NOTHING``
keeps the migration idempotent and safe to re-apply on environments
where these keys were created manually.

Revision ID: 0008_text_kind_and_icon
Revises: 0007_broadcast_buttons_per_row
Create Date: 2026-05-06 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008_text_kind_and_icon"
down_revision: str | None = "0007_broadcast_buttons_per_row"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (key, label, description) — description shows up under the key in admin UI.
_BUTTON_SEEDS: list[tuple[str, str, str]] = [
    # Main menu
    ("btn.main_menu.catalog", "Каталог", "Главное меню → Каталог"),
    ("btn.main_menu.profile", "Профиль", "Главное меню → Профиль"),
    ("btn.main_menu.support", "Поддержка", "Главное меню → Поддержка"),
    ("btn.main_menu.promo", "Промокод", "Главное меню → Промокод"),
    ("btn.main_menu.idea", "Предложить идею", "Главное меню → Предложить идею"),
    ("btn.main_menu.about", "О проекте", "Главное меню → О проекте"),
    # Common navigation
    ("btn.common.back", "← Назад", "Универсальная кнопка возврата"),
    ("btn.common.to_menu", "🏠 В меню", "Возврат в главное меню (после успеха)"),
    ("btn.common.subscribe", "Подписаться", "Гейт обязательной подписки → URL канала"),
    (
        "btn.common.subscribed",
        "Я подписался ✅",
        "Гейт обязательной подписки → проверить статус",
    ),
    # Profile
    (
        "btn.profile.add_more",
        "➕ Оформить ещё",
        "Профиль → купить ещё одну подписку",
    ),
    ("btn.profile.topup", "💰 Пополнить баланс", "Профиль → пополнение баланса"),
    (
        "btn.profile.referral",
        "🎁 Реферальная программа",
        "Профиль → реферальная программа",
    ),
    # Subscription detail
    (
        "btn.subscription.howto",
        "📖 Как подключиться",
        "Подписка → инструкция (если HOWTO_URL не задан)",
    ),
    ("btn.subscription.extend", "♻️ Продлить", "Подписка → продлить"),
    # Top-up / payment methods
    ("btn.payment.sbp", "СБП", "Способ оплаты — СБП"),
    ("btn.payment.cryptobot", "CryptoBot", "Способ оплаты — CryptoBot"),
    ("btn.payment.crypto", "Криптовалюта", "Способ оплаты — Криптовалюта"),
    ("btn.payment.balance", "💰 Баланс", "Способ оплаты — Баланс (доступен)"),
    ("btn.payment.balance_locked", "🔒 Баланс", "Способ оплаты — Баланс (мало средств)"),
    ("btn.payment.pay", "💳 Оплатить", "Внешняя ссылка на страницу оплаты"),
    ("btn.payment.cancel", "← Отменить", "Отмена счёта"),
    # Tickets / support
    ("btn.ticket.create_support", "Создать тикет", "Поддержка → создать тикет"),
    ("btn.ticket.create_idea", "Предложить идею", "Идеи → отправить идею"),
    ("btn.ticket.close_yes", "Да, закрыть", "Подтверждение закрытия тикета"),
    ("btn.ticket.close_no", "Отмена", "Отмена закрытия тикета"),
    # Promo
    ("btn.promo.skip", "Нет промокода", "Промо → пропустить"),
    ("btn.promo.retry", "✏️ Ввести другой", "Промо → ввести другой код"),
    ("btn.promo.skip_alt", "Без промокода", "Промо → продолжить без кода (альт)"),
]


def upgrade() -> None:
    # 1. Add the two columns. ``kind`` is non-null with a default so existing
    #    rows convert silently; ``icon_custom_emoji_id`` is nullable and only
    #    meaningful for ``kind='button'`` rows.
    op.add_column(
        "texts",
        sa.Column(
            "kind",
            sa.String(length=16),
            nullable=False,
            server_default="message",
        ),
    )
    op.add_column(
        "texts",
        sa.Column(
            "icon_custom_emoji_id",
            sa.String(length=64),
            nullable=True,
        ),
    )

    # 2. Seed button rows. Each insert is idempotent — re-running the migration
    #    or applying it after manual key creation is a no-op.
    bind = op.get_bind()
    for key, label, description in _BUTTON_SEEDS:
        bind.execute(
            sa.text(
                """
                INSERT INTO texts (key, value_html, description, kind, updated_at)
                VALUES (:key, :value_html, :description, 'button', NOW())
                ON CONFLICT (key) DO NOTHING
                """
            ),
            {"key": key, "value_html": label, "description": description},
        )


def downgrade() -> None:
    bind = op.get_bind()
    keys = [k for k, _, _ in _BUTTON_SEEDS]
    bind.execute(
        sa.text("DELETE FROM texts WHERE key = ANY(:keys) AND kind = 'button'"),
        {"keys": keys},
    )
    op.drop_column("texts", "icon_custom_emoji_id")
    op.drop_column("texts", "kind")
