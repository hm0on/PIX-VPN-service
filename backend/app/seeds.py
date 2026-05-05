"""Idempotent seeding for Stage 1.

Run via:  python -m app.seeds
"""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.security import hash_secret
from app.db.models.admin_key import AdminKey
from app.db.models.tariff import Tariff, TariffDuration
from app.db.models.text import Text
from app.db.session import get_session_factory
from app.repositories.admin_key_repo import AdminKeyRepository

logger = get_logger("seeds")


# ---------- Tariffs (prices in kopecks; questions.md) ----------

TARIFFS_DATA: list[dict[str, Any]] = [
    {
        "code": "free",
        "name": "FREE",
        "description_html": "<b>3 дня</b> бесплатного теста — 1 устройство.",
        "devices": 1,
        "sort_order": 0,
        "is_free_trial": True,
        "free_trial_days": 3,
        "durations": [],
    },
    {
        "code": "basic",
        "name": "Basic",
        "description_html": "<b>3 устройства</b>. Оптимальный выбор для личного использования.",
        "devices": 3,
        "sort_order": 10,
        "durations": [
            {"days": 30, "price_kopecks": 18900, "is_hot": False},
            {"days": 90, "price_kopecks": 45900, "is_hot": True},
            {"days": 180, "price_kopecks": 119000, "is_hot": False},
            {"days": 365, "price_kopecks": 159000, "is_hot": False},
        ],
    },
    {
        "code": "plus",
        "name": "Plus",
        "description_html": "<b>5 устройств</b>. Для тех, кто ценит комфорт на всех гаджетах.",
        "devices": 5,
        "sort_order": 20,
        "durations": [
            {"days": 30, "price_kopecks": 24900, "is_hot": False},
            {"days": 90, "price_kopecks": 64900, "is_hot": True},
            {"days": 180, "price_kopecks": 169000, "is_hot": False},
            {"days": 365, "price_kopecks": 199000, "is_hot": False},
        ],
    },
    {
        "code": "ultra",
        "name": "Ultra",
        "description_html": "<b>10 устройств</b>. Мощный пакет для активных пользователей и их близких.",
        "devices": 10,
        "sort_order": 30,
        "durations": [
            {"days": 30, "price_kopecks": 39900, "is_hot": False},
            {"days": 90, "price_kopecks": 99000, "is_hot": True},
            {"days": 180, "price_kopecks": 299000, "is_hot": False},
            {"days": 365, "price_kopecks": 349000, "is_hot": False},
        ],
    },
    {
        "code": "max",
        "name": "Max",
        "description_html": "<b>16 устройств</b>. Максимальная свобода без ограничений.",
        "devices": 16,
        "sort_order": 40,
        "durations": [
            {"days": 30, "price_kopecks": 59900, "is_hot": False},
            {"days": 90, "price_kopecks": 149000, "is_hot": True},
            {"days": 180, "price_kopecks": 449000, "is_hot": False},
            {"days": 365, "price_kopecks": 499000, "is_hot": False},
        ],
    },
]


# ---------- Default texts (HTML) ----------

DEFAULT_TEXTS: list[dict[str, str]] = [
    {
        "key": "main_menu",
        "value_html": "<b>Интернет без границ!</b>\nОсновное меню:",
        "description": "Главное меню бота (после /start).",
    },
    {
        "key": "section_in_development",
        "value_html": "<b>Раздел в разработке</b>",
        "description": "Заглушка для нереализованных кнопок.",
    },
    {
        "key": "channel_subscription_required",
        "value_html": (
            "<b>Подпишитесь на канал</b>, чтобы пользоваться ботом.\n"
            "После подписки нажмите кнопку «Я подписался»."
        ),
        "description": "Сообщение при отсутствии подписки на обязательный канал.",
    },
    {
        "key": "banned_user",
        "value_html": "<b>Доступ ограничен.</b> Если считаете это ошибкой — свяжитесь с поддержкой.",
        "description": "Сообщение для забаненных пользователей.",
    },
    {
        "key": "ban_reason_template",
        "value_html": "<b>Причина блокировки:</b> {reason}",
        "description": "Шаблон причины бана. {reason} — текст причины.",
    },
    # ---------- Stage 2: keys / payments / profile / catalog ----------
    {
        "key": "key_issued",
        "value_html": (
            "✅ Вы успешно оплатили заказ <b>#{payment_id}</b>\n\n"
            "Ваш ключ:\n<code>{key_url}</code>"
        ),
        "description": "Сообщение после успешной выдачи ключа после оплаты.",
    },
    {
        "key": "key_issued_free_trial",
        "value_html": (
            "🎁 Ваш бесплатный пробный период активирован!\n\n"
            "Ключ:\n<code>{key_url}</code>\n\n"
            "Действует 3 дня."
        ),
        "description": "Сообщение после активации FREE-триала.",
    },
    {
        "key": "free_trial_already_used",
        "value_html": "Бесплатный пробный период уже был использован на этом аккаунте.",
        "description": "FREE-триал уже использован.",
    },
    {
        "key": "insufficient_balance",
        "value_html": (
            "Недостаточно средств на балансе. Текущий баланс: <b>{balance} ₽</b>. "
            "Пополните баланс в профиле."
        ),
        "description": "Недостаточно средств для оплаты с баланса.",
    },
    {
        "key": "vpn_provider_unavailable",
        "value_html": "Похоже, что-то пошло не так. Обратитесь в поддержку — мы решим.",
        "description": "Ошибка при выдаче ключа (NorthLine недоступен).",
    },
    {
        "key": "refund_after_provider_error",
        "value_html": (
            "Не удалось выдать ключ, средства возвращены на баланс. "
            "Попробуйте позже или обратитесь в поддержку."
        ),
        "description": "Возврат на баланс после ошибки провайдера VPN.",
    },
    {
        "key": "unexpected_error",
        "value_html": (
            "<b>Ой! Что-то пошло не так,</b> попробуйте позже или обратитесь в поддержку."
        ),
        "description": "Универсальная ошибка для пользователя.",
    },
    {
        "key": "service_unavailable",
        "value_html": "<b>Сервис временно недоступен.</b> Попробуйте позже.",
        "description": "Сервис временно недоступен.",
    },
    {
        "key": "profile_header",
        "value_html": (
            "👤 <b>{name}</b>\n"
            "ID: <code>{tg_id}</code> · {username}\n\n"
            "💰 Баланс: <b>{balance} ₽</b>\n"
            "📦 Подписок: <b>{subs_count}</b> · 👥 Рефералов: <b>{invited_count}</b>\n\n"
            "Активные подписки:\n{subscriptions}"
        ),
        "description": "Заголовок раздела «Профиль».",
    },
    {
        "key": "profile_no_subscriptions",
        "value_html": (
            "👤 <b>{name}</b>\n"
            "ID: <code>{tg_id}</code> · {username}\n\n"
            "💰 Баланс: <b>{balance} ₽</b>\n"
            "📦 Подписок: <b>0</b> · 👥 Рефералов: <b>{invited_count}</b>\n\n"
            "У вас пока нет активных подписок."
        ),
        "description": "Профиль: нет активных подписок.",
    },
    {
        "key": "subscription_detail",
        "value_html": (
            "<b>{tariff_name}</b>\nУстройств: {devices}\n"
            "Действует до: {expires_at}\n\n"
            "Ключ:\n<code>{key_url}</code>"
        ),
        "description": "Детали подписки.",
    },
    {
        "key": "catalog_header",
        "value_html": "<b>Каталог тарифов</b>\n\nВыберите подходящий план:",
        "description": "Заголовок каталога тарифов.",
    },
    {
        "key": "tariff_durations_header",
        "value_html": (
            "<b>{tariff_name}</b>\n{tariff_description}\n\nВыберите длительность:"
        ),
        "description": "Список длительностей выбранного тарифа.",
    },
    {
        "key": "pay_method_header",
        "value_html": (
            "<b>Выберите способ оплаты</b>\n\nИтого: <b>{amount} ₽</b>"
        ),
        "description": "Выбор способа оплаты.",
    },
    {
        "key": "topup_amount_prompt",
        "value_html": "Введите сумму пополнения в рублях (минимум 10 ₽):",
        "description": "Запрос суммы пополнения.",
    },
    {
        "key": "topup_min_amount",
        "value_html": "Минимальная сумма пополнения — <b>10 ₽</b>.",
        "description": "Сообщение о минимальной сумме пополнения.",
    },
    {
        "key": "payment_invoice",
        "value_html": (
            "Счёт на оплату <b>#{payment_id}</b>\nСумма: <b>{amount} ₽</b>\n\n"
            "Нажмите кнопку ниже для оплаты."
        ),
        "description": "Сообщение со счётом на оплату.",
    },
    {
        "key": "payment_pending",
        "value_html": "Ожидаем подтверждение оплаты...",
        "description": "Платёж в обработке.",
    },
    {
        "key": "payment_provider_unavailable",
        "value_html": (
            "Похоже, оплата временно недоступна. "
            "Попробуйте позже или обратитесь в поддержку."
        ),
        "description": "Платёжная система недоступна.",
    },
    {
        "key": "topup_success",
        "value_html": (
            "✅ Баланс пополнен на <b>{amount} ₽</b>.\n\n"
            "Текущий баланс: <b>{balance} ₽</b>."
        ),
        "description": "Подтверждение пополнения баланса.",
    },
    # ---------- Stage 3: promo codes ----------
    {
        "key": "promo_input_prompt",
        "value_html": "<b>🎟 Промокод</b>\n\nВведите промокод:",
        "description": "Запрос ввода промокода.",
    },
    {
        "key": "promo_balance_applied",
        "value_html": (
            "<b>✅ Промокод применён</b>\n\n"
            "На баланс зачислено <b>{amount} ₽</b>.\n"
            "Текущий баланс: <b>{balance} ₽</b>."
        ),
        "description": "Промокод-баланс успешно применён.",
    },
    {
        "key": "promo_discount_applied",
        "value_html": (
            "<b>✅ Промокод применён</b>\n\n"
            "Скидка <b>{percent}%</b>. Итоговая сумма: <b>{total} ₽</b>."
        ),
        "description": "Промокод-скидка применён к выбранной длительности.",
    },
    {
        "key": "promo_not_found",
        "value_html": (
            "❌ Этот промокод уже истёк либо не соблюдены условия."
        ),
        "description": "Промокод не найден / истёк / не подходит.",
    },
    {
        "key": "promo_unavailable",
        "value_html": (
            "❌ Этот промокод уже истёк либо не соблюдены условия."
        ),
        "description": "Промокод недоступен (общая ошибка).",
    },
    {
        "key": "promo_already_used_by_user",
        "value_html": (
            "❌ Этот промокод уже истёк либо не соблюдены условия."
        ),
        "description": "Алиас единого сообщения для backward-compat.",
    },
    {
        "key": "promo_discount_requires_purchase",
        "value_html": (
            "🎟 <b>Это промокод на скидку.</b>\n"
            "Чтобы применить его, начните оформление подписки в каталоге — "
            "ввести промокод можно будет на этапе выбора длительности."
        ),
        "description": (
            "Сообщение при вводе скидочного промокода вне покупки."
        ),
    },
    # ---------- Stage 3: referral program ----------
    {
        "key": "referral_bonus_credited",
        "value_html": (
            "<b>🎁 Реферальный бонус!</b>\n\n"
            "По вашей реферальной ссылке зарегистрировался <b>{username}</b> "
            "и оформил подписку.\n"
            "На ваш баланс зачислено <b>100 ₽</b>."
        ),
        "description": "Уведомление рефереру о начислении +100 ₽.",
    },
    {
        "key": "referral_program_screen",
        "value_html": (
            "<b>🎁 Реферальная программа</b>\n\n"
            "Приглашайте друзей и получайте <b>100 ₽</b> на баланс за каждого, "
            "кто оформит подписку!\n"
            "Друзья получат скидку <b>10%</b> на первую покупку.\n\n"
            "Ваша ссылка:\n<code>{ref_link}</code>\n\n"
            "Приглашено: <b>{invited}</b>\n"
            "Заработано: <b>{earned} ₽</b>"
        ),
        "description": "Экран реферальной программы.",
    },
    # ---------- Stage 3: subscription extension ----------
    {
        "key": "subscription_extended",
        "value_html": (
            "<b>✅ Подписка продлена</b>\n\n"
            "Новая дата окончания: <b>{new_expires_at}</b>"
        ),
        "description": "Уведомление о успешном продлении подписки.",
    },
    {
        "key": "subscription_not_extendable",
        "value_html": (
            "❌ Эта подписка не может быть продлена. "
            "Оформите новую через каталог."
        ),
        "description": "Подписка не может быть продлена (expired/deactivated).",
    },
    {
        "key": "extension_failed_refund",
        "value_html": (
            "❌ Не удалось продлить подписку. Деньги вернулись на баланс."
        ),
        "description": "Возврат средств после ошибки продления.",
    },
    # ---------- Stage 4: support tickets ----------
    {
        "key": "support_no_active_ticket",
        "value_html": (
            "<b>💬 Поддержка</b>\n\nУ вас нет активных тикетов."
        ),
        "description": "Раздел Поддержка — нет открытого тикета.",
    },
    {
        "key": "support_active_ticket",
        "value_html": (
            "<b>💬 Тикет {code} открыт</b>\n\n"
            "Напишите сообщение или прикрепите фото — мы получим его."
        ),
        "description": "Раздел Поддержка — открытый тикет.",
    },
    {
        "key": "support_ticket_created",
        "value_html": (
            "<b>Тикет {code} создан.</b>\n\nОпишите вашу проблему."
        ),
        "description": "Подтверждение создания тикета поддержки.",
    },
    {
        "key": "support_ticket_closed_by_user",
        "value_html": (
            "<b>Тикет {code} закрыт.</b>\n\nСпасибо за обращение!"
        ),
        "description": "Юзер сам закрыл тикет.",
    },
    {
        "key": "support_ticket_closed_by_admin",
        "value_html": "<b>Администрация закрыла тикет {code}.</b>",
        "description": "Админ закрыл тикет.",
    },
    {
        "key": "support_already_open",
        "value_html": (
            "У вас уже есть открытый тикет <b>{code}</b>. "
            "Сначала закройте его."
        ),
        "description": "Попытка открыть второй тикет.",
    },
    {
        "key": "support_no_text",
        "value_html": (
            "Чтобы написать в поддержку, создайте тикет в разделе «Поддержка»."
        ),
        "description": "Юзер пишет боту, не открыв тикет.",
    },
    {
        "key": "support_sticker_rejected",
        "value_html": "Стикеры в тикетах не поддерживаются.",
        "description": "Юзер прислал стикер в тикет.",
    },
    {
        "key": "support_unsupported_media",
        "value_html": "Можно отправить только текст или фото.",
        "description": "Юзер прислал документ/видео/etc.",
    },
    {
        "key": "support_flood_limit",
        "value_html": "Слишком много сообщений, подождите.",
        "description": "Антифлуд для тикетов.",
    },
    {
        "key": "support_admin_reply_prefix",
        "value_html": "<b>Поддержка:</b> {text}",
        "description": "Префикс ответа админа юзеру.",
    },
    {
        "key": "support_user_banned_notice",
        "value_html": (
            "<b>Вы заблокированы в боте.</b>\nПричина: {reason}"
        ),
        "description": "Уведомление юзеру о бане.",
    },
    {
        "key": "support_user_unbanned_notice",
        "value_html": "<b>Вы разблокированы в боте.</b>",
        "description": "Уведомление юзеру о разбане.",
    },
    # ---------- Stage 5: admin actions ----------
    {
        "key": "subscription_deactivated_by_admin",
        "value_html": (
            "<b>Ваш ключ #{key_id} деактивирован администратором.</b>\n"
            "Причина: {reason}"
        ),
        "description": "Уведомление юзеру о деактивации ключа админом.",
    },
    {
        "key": "balance_admin_adjusted",
        "value_html": (
            "<b>Баланс изменён администратором</b>\n"
            "Изменение: <b>{delta} ₽</b>\n"
            "Текущий баланс: <b>{balance} ₽</b>\n"
            "Причина: {reason}"
        ),
        "description": "Уведомление юзеру о ручной корректировке баланса.",
    },
    {
        "key": "idea_no_active_ticket",
        "value_html": (
            "<b>💡 Предложить идею</b>\n\n"
            "Опишите вашу идею — мы её рассмотрим."
        ),
        "description": "Раздел «Предложить идею» — нет открытой заявки.",
    },
    {
        "key": "idea_ticket_created",
        "value_html": (
            "<b>Заявка {code} создана.</b>\n\n"
            "Спасибо! Мы рассмотрим вашу идею."
        ),
        "description": "Подтверждение создания заявки на идею.",
    },
    {
        "key": "support_topic_separator",
        "value_html": "<b>━━━ Новый тикет {code} ━━━</b>",
        "description": "Разделитель в топике при переоткрытии.",
    },
    {
        "key": "support_topic_user_message",
        "value_html": (
            "<b>Тикет:</b> {code}\n"
            "<b>Пользователь:</b> {first_name}\n"
            "<b>Юзернейм:</b> {username}\n\n"
            "<b>Сообщение:</b>\n{text}"
        ),
        "description": "Сообщение юзера в топике поддержки.",
    },
    {
        "key": "support_topic_user_idea",
        "value_html": (
            "<b>💡 Предложение идеи</b>\n"
            "<b>Тикет:</b> {code}\n"
            "<b>Пользователь:</b> {first_name}\n"
            "<b>Юзернейм:</b> {username}\n\n"
            "<b>Сообщение:</b>\n{text}"
        ),
        "description": "Сообщение юзера-идеи в топике.",
    },
    {
        "key": "support_topic_user_closed",
        "value_html": "<b>Юзер закрыл тикет {code}.</b>",
        "description": "В топике: юзер закрыл тикет.",
    },
    {
        "key": "support_topic_admin_closed",
        "value_html": "<b>Тикет {code} закрыт администратором.</b>",
        "description": "В топике: админ закрыл тикет.",
    },
    {
        "key": "support_topic_user_banned",
        "value_html": (
            "<b>Юзер {username} заблокирован.</b>\nПричина: {reason}"
        ),
        "description": "В топике: юзер заблокирован.",
    },
    {
        "key": "support_topic_user_unbanned",
        "value_html": "<b>Юзер {username} разблокирован.</b>",
        "description": "В топике: юзер разблокирован.",
    },
    {
        "key": "support_topic_no_open_ticket",
        "value_html": (
            "У юзера нет открытого тикета. Сообщение не доставлено."
        ),
        "description": "Админ написал в топик без открытого тикета.",
    },
    {
        "key": "support_topic_ban_reason_prompt",
        "value_html": (
            "Введите причину блокировки одним сообщением (или /cancel)."
        ),
        "description": "Запрос причины бана от админа.",
    },
]


async def seed_initial_admin_key(session: AsyncSession) -> None:
    settings = get_settings()
    repo = AdminKeyRepository(session)
    usable = await repo.list_usable()
    if usable:
        logger.info("admin_key_seed_skip", reason="already_present", count=len(usable))
        return

    if not settings.admin_initial_key or len(settings.admin_initial_key) < 16:
        logger.warning(
            "admin_key_seed_skip",
            reason="initial_key_missing_or_short",
        )
        return

    key_hash = hash_secret(settings.admin_initial_key)
    row = AdminKey(key_hash=key_hash, label=settings.admin_initial_key_label or "main")
    session.add(row)
    await session.flush()
    logger.info("admin_key_seed_created", label=row.label, kid=row.id)


async def seed_tariffs(session: AsyncSession) -> None:
    for data in TARIFFS_DATA:
        durations_data = data.get("durations", [])
        existing = await session.execute(select(Tariff).where(Tariff.code == data["code"]))
        tariff = existing.scalar_one_or_none()

        if tariff is None:
            tariff = Tariff(
                code=data["code"],
                name=data["name"],
                description_html=data.get("description_html"),
                devices=data["devices"],
                sort_order=data.get("sort_order", 0),
                is_active=True,
                is_free_trial=data.get("is_free_trial", False),
                free_trial_days=data.get("free_trial_days"),
            )
            session.add(tariff)
            await session.flush()
            logger.info("tariff_seed_created", code=tariff.code)
        else:
            # Don't overwrite admin-tweaked descriptions/prices.
            logger.info("tariff_seed_skip", code=tariff.code, reason="exists")

        for d in durations_data:
            stmt = select(TariffDuration).where(
                TariffDuration.tariff_id == tariff.id,
                TariffDuration.days == d["days"],
            )
            res = await session.execute(stmt)
            existing_dur = res.scalar_one_or_none()
            if existing_dur is None:
                session.add(
                    TariffDuration(
                        tariff_id=tariff.id,
                        days=d["days"],
                        price_kopecks=d["price_kopecks"],
                        is_hot=d.get("is_hot", False),
                        is_active=True,
                    )
                )
                logger.info(
                    "tariff_duration_seed_created",
                    tariff=tariff.code,
                    days=d["days"],
                    price_kopecks=d["price_kopecks"],
                )

    await session.flush()


async def seed_texts(session: AsyncSession) -> None:
    for entry in DEFAULT_TEXTS:
        res = await session.execute(select(Text).where(Text.key == entry["key"]))
        existing = res.scalar_one_or_none()
        if existing is None:
            session.add(
                Text(
                    key=entry["key"],
                    value_html=entry["value_html"],
                    description=entry.get("description"),
                )
            )
            logger.info("text_seed_created", key=entry["key"])
    await session.flush()


async def run_seeds() -> None:
    configure_logging(get_settings().log_level)
    factory = get_session_factory()
    async with factory() as session:
        await seed_initial_admin_key(session)
        await seed_tariffs(session)
        await seed_texts(session)
        await session.commit()
    logger.info("seeds_completed")


def main() -> None:
    asyncio.run(run_seeds())


if __name__ == "__main__":
    main()
