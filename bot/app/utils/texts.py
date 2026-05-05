"""TextService — fetches HTML texts (and optional media) from Backend API.

All bot replies use ``parse_mode=HTML``. Texts live in the ``texts`` table on
the backend and are editable from the admin panel; the bot retrieves them
through ``GET /api/bot/texts/{key}`` (or batched ``GET /api/bot/texts``).

Each text may carry an optional Telegram media attachment (photo / video /
animation) referenced by ``file_id``. When present, handlers should call
``send_text_or_media(...)`` so users see one combined message (caption on
the media) instead of plain HTML.

Cache strategy: simple TTL dict (``texts_cache_ttl_seconds``, default 60s)
that covers the whole working set — every refresh re-hydrates from the bulk
endpoint. Stage 5 wires Redis pub/sub invalidation on top.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from app.api_client import BackendClient
from app.utils.errors import BackendUnavailableError
from app.utils.logging import get_logger

log = get_logger("bot.texts")


@dataclass(slots=True, frozen=True)
class TextEntry:
    """A single text record cached from backend."""

    value_html: str
    media_file_id: str | None = None
    media_kind: str | None = None  # "photo" | "video" | "animation" | None


# Hardcoded fallback for when Backend is unreachable AND no cached value.
# These are the bare minimum strings used in middlewares — everything else
# falls back to a `[text:KEY not found]` placeholder, which is loud-on-purpose
# so missing keys are obvious in production.
_HARDCODED_FALLBACKS: dict[str, str] = {
    # ---- Stage 1 critical strings (also used by middlewares) --------------
    "service_unavailable": (
        "<b>Сервис временно недоступен.</b>\n"
        "Попробуйте, пожалуйста, чуть позже."
    ),
    "unexpected_error": (
        "<b>Ой! Что-то пошло не так.</b>\n"
        "Попробуйте позже или обратитесь в поддержку."
    ),
    "channel_subscription_required": (
        "<b>Подпишитесь на наш канал</b>, чтобы пользоваться ботом."
    ),
    "banned_user": "Вы заблокированы и не можете пользоваться ботом.",
    "section_in_development": "<b>Раздел в разработке</b> 🛠",
    "main_menu": "<b>Интернет без границ!</b>\nОсновное меню:",
    # ---- Stage 2: catalog / purchase / profile ----------------------------
    "catalog_header": "<b>Каталог</b>\nВыберите тариф:",
    "tariff_durations_header": (
        "<b>{tariff_name}</b>\n{description}\n\nВыберите длительность:"
    ),
    "promo_input_prompt": (
        "<b>Введите промокод:</b>\nИли нажмите «Нет промокода», чтобы продолжить."
    ),
    "pay_method_header": (
        "К оплате: <b>{amount} ₽</b>\nВыберите способ оплаты:"
    ),
    "payment_invoice": (
        "💳 <b>Счёт #{payment_id}</b>\n"
        "Сумма: <b>{amount} ₽</b>\n\n"
        "Нажмите «Оплатить», чтобы перейти на страницу провайдера."
    ),
    "key_issued": (
        "✅ Вы успешно оплатили заказ <b>#{payment_id}</b>\n\n"
        "Ваш ключ:\n<code>{key_url}</code>"
    ),
    "key_issued_free_trial": (
        "🎁 <b>Бесплатный пробный период активирован!</b>\n\n"
        "Ваш ключ:\n<code>{key_url}</code>\n\n"
        "Срок: {days} дн. · Устройств: {devices}."
    ),
    # ---- Stage 2: error keys ---------------------------------------------
    "free_trial_already_used": (
        "Бесплатный пробный период уже был использован на этом аккаунте."
    ),
    "vpn_provider_unavailable": (
        "Сервис выдачи ключей временно недоступен. "
        "Попробуйте позже или обратитесь в поддержку."
    ),
    "payment_provider_unavailable": (
        "Похоже, оплата временно недоступна. "
        "Попробуйте позже или обратитесь в поддержку."
    ),
    "insufficient_balance": (
        "Недостаточно средств на балансе. "
        "Текущий баланс: <b>{balance} ₽</b>. "
        "Пополните баланс в профиле."
    ),
    "refund_after_provider_error": (
        "Не удалось выдать ключ — средства возвращены на баланс. "
        "Попробуйте позже или обратитесь в поддержку."
    ),
    # ---- Stage 2: profile -------------------------------------------------
    "profile_header": (
        "👤 <b>Ваш профиль</b>\n\n"
        "Баланс: <b>{balance} ₽</b>\n\n"
        "Активные подписки:\n{subscriptions}"
    ),
    "profile_no_subscriptions": (
        "👤 <b>Ваш профиль</b>\n\n"
        "Баланс: <b>{balance} ₽</b>\n\n"
        "У вас пока нет активных подписок."
    ),
    "subscription_detail": (
        "<b>{tariff_name}</b>\n"
        "Устройств: {devices} · Дней: {days}\n"
        "Активирована: {started_at}\n"
        "Действует до: {expires_at}\n\n"
        "Ключ:\n<code>{key_url}</code>"
    ),
    "howto_connect_fallback": (
        "Инструкция по подключению скоро появится. Если возникли вопросы — "
        "напишите в поддержку."
    ),
    # ---- Stage 2: top-up --------------------------------------------------
    "topup_amount_prompt": (
        "💰 <b>Пополнение баланса</b>\n\n"
        "Введите сумму в рублях (минимум {min_amount} ₽):"
    ),
    "topup_invalid_amount": (
        "Не удалось распознать сумму. Введите целое число рублей "
        "(минимум {min_amount} ₽)."
    ),
    "topup_min_amount": (
        "Минимальная сумма пополнения — <b>{min_amount} ₽</b>. "
        "Попробуйте ещё раз."
    ),
    "topup_method_prompt": (
        "К пополнению: <b>{amount} ₽</b>\nВыберите способ оплаты:"
    ),
    # ---- Stage 3: promo --------------------------------------------------
    "promo_balance_applied": (
        "🎉 <b>Промокод применён!</b>\n"
        "На баланс зачислено <b>{amount} ₽</b>.\n"
        "Текущий баланс: <b>{balance} ₽</b>."
    ),
    "promo_discount_applied": (
        "✅ <b>Скидка {percent}% применена.</b>\n"
        "Итоговая сумма: <b>{amount} ₽</b>\n\n"
        "Выберите способ оплаты:"
    ),
    "promo_not_found": (
        "Этот промокод не найден, истёк либо не соблюдены условия. "
        "Попробуйте другой или продолжите без промокода."
    ),
    "promo_unavailable": (
        "Промокод сейчас недоступен. "
        "Попробуйте другой или продолжите без промокода."
    ),
    # ---- Stage 3: referral ----------------------------------------------
    "referral_program_screen": (
        "🎁 <b>Реферальная программа</b>\n\n"
        "Приглашайте друзей и получайте <b>100 ₽</b> на баланс за каждого, "
        "кто оформит подписку!\n"
        "Друзья получат скидку <b>10%</b> на первую покупку.\n\n"
        "Ваша ссылка:\n<code>{ref_link}</code>\n\n"
        "Приглашено: <b>{count}</b>\n"
        "Заработано: <b>{earned} ₽</b>"
    ),
    "referral_bonus_credited": (
        "🎉 По вашей реферальной ссылке зарегистрировался новый пользователь!\n"
        "На баланс зачислено <b>100 ₽</b>."
    ),
    # ---- Stage 3: extension ---------------------------------------------
    "extension_select_duration": (
        "<b>📅 Продление подписки</b>\n\nВыберите срок продления:"
    ),
    "subscription_extended": (
        "<b>✅ Подписка продлена до {new_expires_at}</b>"
    ),
    "subscription_not_extendable": (
        "Эту подписку нельзя продлить — она истекла или была деактивирована. "
        "Оформите новую в каталоге."
    ),
    "extension_failed_refund": (
        "Не удалось продлить подписку — средства возвращены на баланс. "
        "Попробуйте позже или обратитесь в поддержку."
    ),
    # ---- Stage 4: support tickets / ideas / ban -------------------------
    "support_no_active_ticket": (
        "💬 <b>Поддержка</b>\n\n"
        "У вас нет активных тикетов."
    ),
    "support_active_ticket": (
        "💬 <b>Тикет {code} открыт</b>\n\n"
        "Напишите сообщение или прикрепите фото — мы получим его."
    ),
    "support_ticket_created": (
        "✅ <b>Тикет {code} создан.</b>\n\n"
        "Опишите вашу проблему — мы скоро ответим."
    ),
    "support_already_open": (
        "У вас уже есть открытый тикет <b>{code}</b>. "
        "Закройте его, прежде чем открыть новый."
    ),
    "support_ticket_closed_by_user": (
        "Тикет <b>{code}</b> закрыт. Спасибо за обращение!"
    ),
    "support_ticket_closed_by_admin": (
        "Администрация закрыла тикет <b>{code}</b>."
    ),
    "support_close_cancelled": "Тикет не закрыт.",
    "support_sticker_rejected": (
        "Стикеры в тикетах не поддерживаются."
    ),
    "support_unsupported_media": (
        "Можно отправить только текст или фото."
    ),
    "support_flood_limit": (
        "Слишком много сообщений, подождите минуту."
    ),
    "support_outside_ticket_nudge": (
        "Чтобы написать в поддержку, создайте тикет в разделе «Поддержка»."
    ),
    "idea_no_active_ticket": (
        "💡 <b>Предложить идею</b>\n\n"
        "Поделитесь идеей — откройте тикет, и мы её рассмотрим."
    ),
    "idea_active_ticket": (
        "💡 <b>Идея {code} в работе</b>\n\n"
        "Напишите подробности или прикрепите фото."
    ),
    "idea_ticket_created": (
        "✅ <b>Идея {code} принята.</b>\n\n"
        "Опишите её — мы прочитаем."
    ),
    # ---- Stage 4: ban / unban DM notifications -------------------------
    "support_user_banned_notice": (
        "🚫 Вы заблокированы в боте.\n"
        "Причина: {reason}"
    ),
    "support_user_unbanned_notice": (
        "✅ Вы разблокированы в боте."
    ),
    "user_banned_notice": (
        "🚫 Вы заблокированы в боте.\n"
        "Причина: {reason}"
    ),
    "user_unbanned_notice": (
        "✅ Вы разблокированы в боте."
    ),
    # ---- Stage 4: admin-topic helper messages (used by the admin agent) -
    "support_topic_user_message": (
        "<b>Тикет:</b> {code}\n"
        "<b>Пользователь:</b> {first_name}\n"
        "<b>Юзернейм:</b> {username}\n\n"
        "<b>Сообщение:</b>\n{text}"
    ),
    "support_topic_user_idea": (
        "<b>💡 Предложение идеи</b>\n"
        "<b>Тикет:</b> {code}\n"
        "<b>Пользователь:</b> {first_name}\n"
        "<b>Юзернейм:</b> {username}\n\n"
        "<b>Сообщение:</b>\n{text}"
    ),
    "support_topic_separator": (
        "<b>━━━ Новый тикет {code} ━━━</b>"
    ),
    "support_topic_user_closed": (
        "<b>Юзер закрыл тикет {code}</b>"
    ),
    "support_topic_admin_closed": (
        "Тикет {code} закрыт администратором."
    ),
    "support_topic_user_banned": (
        "Юзер {username} заблокирован: {reason}"
    ),
    "support_topic_user_unbanned": (
        "Юзер {username} разблокирован."
    ),
    "support_topic_no_open_ticket": (
        "У юзера нет открытого тикета. Сообщение не доставлено."
    ),
    "admin_reply_prefix": "<b>Поддержка:</b> {text}",
}


class TextService:
    """Caches HTML texts (with optional media) in-memory; renders via ``str.format``."""

    def __init__(self, api: BackendClient, ttl_seconds: int = 60) -> None:
        self._api = api
        self._ttl = ttl_seconds
        self._cache: dict[str, TextEntry] = {}
        self._expires_at: float = 0.0
        self._lock = asyncio.Lock()

    async def _refresh(self) -> None:
        """(Re)load all texts from backend. Holds a lock to coalesce callers."""
        async with self._lock:
            now = time.monotonic()
            if now < self._expires_at and self._cache:
                return
            try:
                raw = await self._api.get_all_texts()
            except BackendUnavailableError as exc:
                log.warning("texts.refresh_failed", error=str(exc))
                return
            self._cache = {
                key: TextEntry(
                    value_html=item.get("value_html") or "",
                    media_file_id=item.get("media_file_id"),
                    media_kind=item.get("media_kind"),
                )
                for key, item in raw.items()
            }
            self._expires_at = now + self._ttl
            log.debug("texts.refreshed", count=len(self._cache))

    def _resolve(self, key: str) -> TextEntry | None:
        entry = self._cache.get(key)
        if entry is not None:
            return entry
        fallback = _HARDCODED_FALLBACKS.get(key)
        if fallback is not None:
            return TextEntry(value_html=fallback)
        return None

    @staticmethod
    def _format(template: str, **kwargs: object) -> str:
        if not kwargs:
            return template
        try:
            return template.format(**kwargs)
        except (KeyError, IndexError, ValueError) as exc:
            log.warning("texts.format_error", error=str(exc))
            return template

    async def get(self, key: str, /, **kwargs: object) -> str:
        """Return the rendered HTML text for ``key`` (no media awareness)."""
        if time.monotonic() >= self._expires_at or key not in self._cache:
            await self._refresh()

        entry = self._resolve(key)
        if entry is None:
            log.warning("texts.missing_key", key=key)
            return f"<i>[text:{key} not found]</i>"
        return self._format(entry.value_html, **kwargs)

    async def get_entry(self, key: str, /, **kwargs: object) -> TextEntry:
        """Return ``TextEntry`` (rendered HTML + optional media) for ``key``.

        Use this when you want to send the bot's reply via ``send_text_or_media``
        and have it automatically attach a photo/video/animation when the
        operator has configured one for this key in the admin panel.
        """
        if time.monotonic() >= self._expires_at or key not in self._cache:
            await self._refresh()

        entry = self._resolve(key)
        if entry is None:
            log.warning("texts.missing_key", key=key)
            return TextEntry(value_html=f"<i>[text:{key} not found]</i>")
        return TextEntry(
            value_html=self._format(entry.value_html, **kwargs),
            media_file_id=entry.media_file_id,
            media_kind=entry.media_kind,
        )

    def invalidate(self) -> None:
        """Drop the cache (forces a refresh on the next ``get``)."""
        self._cache.clear()
        self._expires_at = 0.0


# ---------------------------------------------------------------------------
# Send helper — text or media-with-caption, transparent to the caller.
# ---------------------------------------------------------------------------


async def send_text_or_media(
    chat_id: int,
    entry: TextEntry,
    *,
    bot: Any,
    reply_markup: Any = None,
    disable_web_page_preview: bool = True,
) -> Any:
    """Send the ``entry`` to ``chat_id`` as plain HTML or as a media+caption.

    - If ``entry.media_file_id`` is set, dispatch ``send_photo``/``send_video``/
      ``send_animation`` with ``caption=value_html``.
    - Otherwise, ``send_message``.

    Telegram caption limit is 1024 chars (vs 4096 for plain messages). If the
    caption would overflow, we send the media first (without caption) and the
    text as a follow-up message — this is rare for the curated copy in our
    ``texts`` table but keeps the helper safe.
    """
    text = entry.value_html
    file_id = entry.media_file_id
    kind = entry.media_kind

    if not file_id or not kind:
        return await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            disable_web_page_preview=disable_web_page_preview,
        )

    caption_limit = 1024
    use_caption = len(text) <= caption_limit
    common = {"chat_id": chat_id}

    if use_caption:
        common["caption"] = text  # type: ignore[assignment]
        common["reply_markup"] = reply_markup  # type: ignore[assignment]

    if kind == "photo":
        msg = await bot.send_photo(photo=file_id, **common)
    elif kind == "video":
        msg = await bot.send_video(video=file_id, **common)
    elif kind == "animation":
        msg = await bot.send_animation(animation=file_id, **common)
    else:
        # Unknown kind — fall back to plain text so the user always sees something.
        log.warning("texts.unknown_media_kind", kind=kind)
        return await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            disable_web_page_preview=disable_web_page_preview,
        )

    if not use_caption:
        # Caption was too long — send the text as a follow-up.
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            disable_web_page_preview=disable_web_page_preview,
        )
    return msg
