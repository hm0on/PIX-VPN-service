"""Update text rows that hard-code outdated trial/referral copy.

``seed_texts`` only INSERTs on first-run and never updates existing rows
(``ON CONFLICT (key) DO NOTHING``). Pre-existing prod rows therefore
still hard-code "3 дня", "1 устройство", "10%", and "100 ₽" — values
that no longer match the conversion pack (5 days / 2 devices /
unlimited-traffic trial, 15% referral discount, 70 ₽ referrer bonus).

To roll out the new copy without an admin manually re-saving each text
in the panel, this data-migration overwrites those rows **only** when
their current ``value_html`` exactly matches the prior seed text. If an
admin already customised a row in the panel, the UPDATE skips it
(``WHERE value_html = :old``) and the admin's wording wins. Worst case
the admin's row still says "100 ₽" — fixable from the panel.

No-op downgrade — rolling back the copy would create more confusion
than it fixes; admins can edit back via the panel if needed.

Revision ID: 0017_conversion_pack_texts
Revises: 0016_conversion_pack
Create Date: 2026-05-13 12:10:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0017_conversion_pack_texts"
down_revision: str | None = "0016_conversion_pack"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (key, old_value_html, new_value_html)
_UPDATES: list[tuple[str, str, str]] = [
    (
        "key_issued_free_trial",
        (
            "🎁 Ваш бесплатный пробный период активирован!\n\n"
            "Ключ:\n<code>{key_url}</code>\n\n"
            "Действует 3 дня."
        ),
        (
            "🎁 Ваш бесплатный пробный период активирован!\n\n"
            "Ключ:\n<code>{key_url}</code>\n\n"
            "<b>5 дней</b> · 2 устройства · безлимитный трафик."
        ),
    ),
    (
        "free_trial_reissued",
        (
            "🎁 <b>Ваш FREE-ключ обновлён</b>\n\n"
            "Мы изменили конфигурацию бесплатного тарифа и перевыпустили "
            "ваш ключ. Старый ключ больше не работает — используйте новый:\n\n"
            "<code>{key_url}</code>\n\n"
            "Действует 3 дня."
        ),
        (
            "🎁 <b>Ваш FREE-ключ обновлён</b>\n\n"
            "Мы изменили конфигурацию бесплатного тарифа и перевыпустили "
            "ваш ключ. Старый ключ больше не работает — используйте новый:\n\n"
            "<code>{key_url}</code>\n\n"
            "<b>5 дней</b> · 2 устройства · безлимитный трафик."
        ),
    ),
    (
        "referral_bonus_credited",
        (
            "<b>🎁 Реферальный бонус!</b>\n\n"
            "По вашей реферальной ссылке зарегистрировался <b>{username}</b> "
            "и оформил подписку.\n"
            "На ваш баланс зачислено <b>100 ₽</b>."
        ),
        (
            "<b>🎁 Реферальный бонус!</b>\n\n"
            "По вашей реферальной ссылке зарегистрировался <b>{username}</b> "
            "и оформил подписку.\n"
            "На ваш баланс зачислено <b>70 ₽</b>."
        ),
    ),
    (
        "referral_program_screen",
        (
            "<b>🎁 Реферальная программа</b>\n\n"
            "Приглашайте друзей и получайте <b>100 ₽</b> на баланс за каждого, "
            "кто оформит подписку!\n"
            "Друзья получат скидку <b>10%</b> на первую покупку.\n\n"
            "Ваша ссылка:\n<code>{ref_link}</code>\n\n"
            "Приглашено: <b>{invited}</b>\n"
            "Заработано: <b>{earned} ₽</b>"
        ),
        (
            "<b>🎁 Реферальная программа</b>\n\n"
            "Приглашайте друзей и получайте бонусы:\n"
            "• Промокод <b>15%</b> когда друг возьмёт бесплатный пробный период\n"
            "• <b>70 ₽</b> на баланс когда друг оформит платную подписку\n\n"
            "Друзья получат скидку <b>15%</b> на первую покупку.\n\n"
            "Ваша ссылка:\n<code>{ref_link}</code>\n\n"
            "Приглашено: <b>{invited}</b>\n"
            "Заработано: <b>{earned} ₽</b>"
        ),
    ),
]


def upgrade() -> None:
    bind = op.get_bind()
    for key, old, new in _UPDATES:
        bind.execute(
            sa.text(
                """
                UPDATE texts
                   SET value_html = :new,
                       updated_at = NOW()
                 WHERE key = :key
                   AND value_html = :old
                """
            ),
            {"key": key, "old": old, "new": new},
        )

    # ------------------------------------------------------------------ #
    # Conversion-pack 2026-05-13: пересмотр платных тарифов.
    # ------------------------------------------------------------------ #
    # Basic: 3 устр → 2 устр / безлимит трафика / 10 GB LTE.
    # Plus:  5 устр → 4 устр / безлимит трафика / 15 GB LTE.
    # Max:   16 устр → 10 устр / безлимит трафика / 30 GB LTE.
    # Ultra: удаляется полностью (юзер подтвердил: ни одной активной
    # подписки нет). Если миграция увидит хоть одну подписку,
    # ссылающуюся на ultra-тариф, она НЕ удалит строки и просто
    # deactivate'нет тариф — иначе FK ondelete=RESTRICT уронит upgrade.
    bind.execute(
        sa.text(
            """
            UPDATE tariffs
               SET devices = 2,
                   traffic_gb_per_month = NULL,
                   lte_gb_per_month = 10,
                   description_html = :basic_desc
             WHERE code = 'basic'
            """
        ),
        {
            "basic_desc": (
                "<b>2 устройства</b>. Безлимитный трафик · 10 GB LTE."
            )
        },
    )
    bind.execute(
        sa.text(
            """
            UPDATE tariffs
               SET devices = 4,
                   traffic_gb_per_month = NULL,
                   lte_gb_per_month = 15,
                   description_html = :plus_desc
             WHERE code = 'plus'
            """
        ),
        {
            "plus_desc": (
                "<b>4 устройства</b>. Безлимитный трафик · 15 GB LTE."
            )
        },
    )
    bind.execute(
        sa.text(
            """
            UPDATE tariffs
               SET devices = 10,
                   traffic_gb_per_month = NULL,
                   lte_gb_per_month = 30,
                   description_html = :max_desc
             WHERE code = 'max'
            """
        ),
        {
            "max_desc": (
                "<b>10 устройств</b>. Безлимитный трафик · 30 GB LTE."
            )
        },
    )

    # Ultra: удаляем. Проверка референсов сначала — если есть подписка,
    # ссылающаяся на ultra-tariff, ondelete=RESTRICT уронит миграцию.
    # Тогда деградируем до soft-delete (is_active=false).
    ultra_refs = bind.execute(
        sa.text(
            """
            SELECT count(*) FROM subscriptions s
              JOIN tariffs t ON t.id = s.tariff_id
             WHERE t.code = 'ultra'
            """
        )
    ).scalar_one()

    if ultra_refs and int(ultra_refs) > 0:
        # Подписки есть — не сносим, просто прячем из каталога.
        bind.execute(
            sa.text(
                """
                UPDATE tariffs SET is_active = FALSE WHERE code = 'ultra';
                UPDATE tariff_durations
                   SET is_active = FALSE
                 WHERE tariff_id IN (SELECT id FROM tariffs WHERE code = 'ultra');
                """
            )
        )
    else:
        # Безопасно сносим строки. tariff_durations имеет ondelete=CASCADE
        # на tariff_id → durations улетят автоматически. Сначала явный
        # DELETE для durations на случай, если миграция cascade не
        # настроена на стороне базы (наша 0001-я ставит CASCADE, но
        # подстрахуемся).
        bind.execute(
            sa.text(
                """
                DELETE FROM tariff_durations
                 WHERE tariff_id IN (SELECT id FROM tariffs WHERE code = 'ultra')
                """
            )
        )
        bind.execute(sa.text("DELETE FROM tariffs WHERE code = 'ultra'"))

    # ------------------------------------------------------------------ #
    # Conversion-pack 2026-05-13: re-grant FREE trial to existing users.
    # ------------------------------------------------------------------ #
    # Бизнес-решение: дать всем «бывалым» юзерам ещё раз опробовать
    # обновлённый триал (5д / 2 устр / безлимит вместо 3д / 1 устр).
    # `FreeTrialService.is_free_trial_used` смотрит ровно одно условие
    # — `EXISTS Subscription WHERE user_id=? AND is_free_trial=TRUE`.
    # Сбрасываем флаг у всех ранее активированных триалов, тогда чек
    # пройдёт и юзер сможет взять новый. Новым юзерам по-прежнему
    # достанется только один триал, потому что новая запись опять
    # получит `is_free_trial=TRUE`.
    #
    # Жёстко привязываемся ко времени запуска миграции (`NOW()`),
    # чтобы любая активация триала, прилетевшая в момент upgrade'а,
    # не попала в UPDATE и не сломала «новый юзер = один триал».
    # Логи / аналитику теряем (старые триалы перестанут считаться),
    # но юзер прямо подтвердил такой trade-off.
    bind.execute(
        sa.text(
            """
            UPDATE subscriptions
               SET is_free_trial = FALSE
             WHERE is_free_trial = TRUE
               AND created_at < NOW()
            """
        )
    )


def downgrade() -> None:
    # No-op: rolling back the copy is more disruptive than helpful.
    # Admins can edit via the panel if needed.
    # Ultra-тариф восстанавливать не пытаемся — если откатываемся, его
    # можно ввести руками через админку.
    pass
