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
import re
import time
from dataclasses import dataclass
from typing import Any

from app.api_client import BackendClient
from app.utils.errors import BackendUnavailableError
from app.utils.logging import get_logger

log = get_logger("bot.texts")


# ---------------------------------------------------------------------------
# Telegram-HTML normalization
# ---------------------------------------------------------------------------
#
# Texts edited in the admin TipTap editor come out as semantic HTML — paragraphs
# wrapped in ``<p>...</p>``, lists rendered as ``<ul><li>...</li></ul>`` etc. —
# but Telegram's HTML parse mode only understands a tiny whitelist of inline
# tags (``b/i/u/s/a/code/pre/blockquote/tg-spoiler/tg-emoji``). Sending a body
# that contains ``<p>`` makes Telegram reject the message with::
#
#     Bad Request: can't parse entities: Unsupported start tag "p" ...
#
# On top of that, when an admin pastes a custom-emoji shortcode like
# ``<tg-emoji emoji-id="...">⭐</tg-emoji>`` into TipTap, ProseMirror doesn't
# know that node and serialises the raw text back as ``&lt;tg-emoji ...&gt;⭐
# &lt;/tg-emoji&gt;`` — visible junk in the bot, not a real custom emoji.
#
# We normalize on the *read* path so:
#   * the admin can keep using TipTap with its natural HTML output,
#   * legacy DB rows with ``<p>``/escaped tags self-heal on the next fetch,
#   * we don't bake an HTML parser into the writer (admin) — bot is the only
#     consumer that actually sends to Telegram.
#
# Anything outside the supported tag whitelist is stripped (the inner text is
# preserved). Whitespace around block elements collapses into newlines. The
# function is intentionally simple regex-based: TipTap's output is well-formed
# enough that we don't need a full parser, and any junk we miss surfaces as
# visible text rather than a 400 from Telegram.

_TG_ALLOWED_TAGS: frozenset[str] = frozenset(
    {
        "b",
        "strong",
        "i",
        "em",
        "u",
        "ins",
        "s",
        "strike",
        "del",
        "a",
        "code",
        "pre",
        "blockquote",
        "tg-spoiler",
        "tg-emoji",
        "span",  # only ``class="tg-spoiler"`` survives — see below
    }
)

# Catch the most common double-escaped patterns the TipTap save path produces
# when an admin types a literal ``<tg-emoji>`` snippet inside the editor.
_RE_ESCAPED_TG_EMOJI = re.compile(
    r"&lt;tg-emoji\s+emoji-id=&quot;(?P<id>\d+)&quot;&gt;"
    r"(?P<inner>.*?)"
    r"&lt;/tg-emoji&gt;",
    re.DOTALL,
)
_RE_ESCAPED_TG_EMOJI_RAW_QUOTE = re.compile(
    r"&lt;tg-emoji\s+emoji-id=\"(?P<id>\d+)\"&gt;"
    r"(?P<inner>.*?)"
    r"&lt;/tg-emoji&gt;",
    re.DOTALL,
)

# Block-level tags whose closing should produce a paragraph break. The opening
# tag is dropped (the content stays).
_BLOCK_TAGS_DOUBLE_BREAK = ("p", "div", "h1", "h2", "h3", "h4", "h5", "h6")
# Block-level tags whose closing produces a single newline (list items).
_BLOCK_TAGS_SINGLE_BREAK = ("li",)

_RE_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)
_RE_OPEN_TAG = re.compile(r"<([a-zA-Z][a-zA-Z0-9-]*)(\s+[^>]*)?>")
_RE_CLOSE_TAG = re.compile(r"</([a-zA-Z][a-zA-Z0-9-]*)\s*>")
# Span class="tg-spoiler" → tg-spoiler tag. Anything else with span is dropped.
#
# The regex is intentionally lenient about the class attribute value: TipTap
# (or any other source) may emit additional class tokens alongside our own
# (e.g. ``class="ProseMirror-tg-spoiler tg-spoiler"`` — depends on how the
# editor merges attributes). We accept the spoiler whenever ``tg-spoiler``
# appears as a whitespace-delimited token inside a quoted ``class`` value,
# regardless of attribute order or surrounding tokens.
_RE_SPAN_SPOILER_OPEN = re.compile(
    r"""
    <span\b                                # opening tag
    [^>]*?                                 # any other attributes
    \bclass\s*=\s*                         # class attribute
    (?P<q>["'])                            # opening quote (captured)
    (?:[^"'>]*\s)?tg-spoiler(?:\s[^"'>]*)? # tg-spoiler as a whole class token
    (?P=q)                                 # matching closing quote
    [^>]*                                  # any trailing attributes
    >
    """,
    re.IGNORECASE | re.VERBOSE,
)
_RE_SPAN_OPEN = re.compile(r"<span(\s+[^>]*)?>", re.IGNORECASE)
_RE_SPAN_CLOSE = re.compile(r"</span\s*>", re.IGNORECASE)


def _normalize_message_html(html: str) -> str:
    """Turn admin-editor HTML into Telegram-friendly HTML.

    Strategy: a single forward pass with regexes. Order matters — emoji
    un-escaping has to run before tag stripping so the un-escaped ``<tg-emoji>``
    survives the whitelist filter; ``<br>`` and block tags get replaced with
    newlines before generic tag-stripping so we don't accidentally glue
    paragraphs together.
    """
    if not html:
        return html

    # 1) Un-escape ``<tg-emoji>`` snippets that ended up double-escaped in DB.
    def _emoji_sub(m: re.Match[str]) -> str:
        return f'<tg-emoji emoji-id="{m.group("id")}">{m.group("inner")}</tg-emoji>'

    out = _RE_ESCAPED_TG_EMOJI.sub(_emoji_sub, html)
    out = _RE_ESCAPED_TG_EMOJI_RAW_QUOTE.sub(_emoji_sub, out)

    # 2) ``<br>`` → newline.
    out = _RE_BR.sub("\n", out)

    # 3) Closing block tags → newline(s). Opening block tags → drop.
    for tag in _BLOCK_TAGS_DOUBLE_BREAK:
        out = re.sub(rf"</{tag}\s*>", "\n\n", out, flags=re.IGNORECASE)
        out = re.sub(rf"<{tag}(\s+[^>]*)?>", "", out, flags=re.IGNORECASE)
    for tag in _BLOCK_TAGS_SINGLE_BREAK:
        out = re.sub(rf"</{tag}\s*>", "\n", out, flags=re.IGNORECASE)
        # Bullet for list items.
        out = re.sub(rf"<{tag}(\s+[^>]*)?>", "• ", out, flags=re.IGNORECASE)

    # 4) Drop list containers — items already became "• " + "\n".
    out = re.sub(r"</?(ul|ol)\s*[^>]*>", "", out, flags=re.IGNORECASE)

    # 5) <span class="tg-spoiler"> → <tg-spoiler>; other <span> → drop tag.
    #
    # We can't use independent regex.sub passes here: a non-spoiler ``<span>``
    # followed by ``</span>`` would leave an orphan close that the next pass
    # converts to ``</tg-spoiler>``, producing unbalanced spoilers in the
    # output. Instead we do one ordered pass and track which open ``<span>``
    # actually became a spoiler so we know whether to close it as
    # ``</tg-spoiler>`` or drop it.
    parts: list[str] = []
    cursor = 0
    span_stack: list[bool] = []  # True if the open span produced a spoiler
    while cursor < len(out):
        m_open = _RE_SPAN_OPEN.search(out, cursor)
        m_close = _RE_SPAN_CLOSE.search(out, cursor)
        # Pick whichever comes first.
        if m_open is not None and (m_close is None or m_open.start() < m_close.start()):
            parts.append(out[cursor : m_open.start()])
            opened_text = m_open.group(0)
            if _RE_SPAN_SPOILER_OPEN.fullmatch(opened_text):
                parts.append("<tg-spoiler>")
                span_stack.append(True)
            else:
                # Generic <span> — drop the tag, content stays.
                span_stack.append(False)
            cursor = m_open.end()
        elif m_close is not None:
            parts.append(out[cursor : m_close.start()])
            is_spoiler = span_stack.pop() if span_stack else False
            if is_spoiler:
                parts.append("</tg-spoiler>")
            cursor = m_close.end()
        else:
            parts.append(out[cursor:])
            break
    # Close any spoilers the user forgot to close (defensive).
    for is_spoiler in reversed(span_stack):
        if is_spoiler:
            parts.append("</tg-spoiler>")
    out = "".join(parts)

    # 6) Strip any remaining tags that aren't in the Telegram whitelist.
    def _strip_unknown_open(m: re.Match[str]) -> str:
        tag = m.group(1).lower()
        if tag in _TG_ALLOWED_TAGS:
            return m.group(0)
        return ""

    def _strip_unknown_close(m: re.Match[str]) -> str:
        tag = m.group(1).lower()
        if tag in _TG_ALLOWED_TAGS:
            return m.group(0)
        return ""

    out = _RE_OPEN_TAG.sub(_strip_unknown_open, out)
    out = _RE_CLOSE_TAG.sub(_strip_unknown_close, out)

    # 7) Collapse runs of 3+ newlines down to a paragraph break.
    out = re.sub(r"\n{3,}", "\n\n", out)

    return out.strip()


@dataclass(slots=True, frozen=True)
class TextEntry:
    """A single text record cached from backend.

    For ``kind='message'`` rows ``value_html`` is the rendered HTML body and
    ``media_*`` may carry an attachment (see :func:`send_text_or_media`). For
    ``kind='button'`` rows ``value_html`` is the plain label string and
    ``icon_custom_emoji_id`` may carry a Telegram custom-emoji document id
    that the bot should pass to ``InlineKeyboardButton.icon_custom_emoji_id``.
    """

    value_html: str
    media_file_id: str | None = None
    media_kind: str | None = None  # "photo" | "video" | "animation" | None
    kind: str = "message"
    icon_custom_emoji_id: str | None = None
    # ``url`` is only meaningful for ``kind='button'`` rows: when set the bot
    # renders the button as an outbound URL button instead of a callback one.
    url: str | None = None


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
        "<b>{tariff_name}</b>\n{tariff_description}\n\nВыберите длительность:"
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
    "key_issuing": "⏳ <b>Выдаём ключ...</b>",
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
        "👤 <b>{name}</b>\n"
        "ID: <code>{tg_id}</code> · {username}\n\n"
        "💰 Баланс: <b>{balance} ₽</b>\n"
        "📦 Подписок: <b>{subs_count}</b> · 👥 Рефералов: <b>{invited_count}</b>\n\n"
        "Активные подписки:\n{subscriptions}"
    ),
    "profile_no_subscriptions": (
        "👤 <b>{name}</b>\n"
        "ID: <code>{tg_id}</code> · {username}\n\n"
        "💰 Баланс: <b>{balance} ₽</b>\n"
        "📦 Подписок: <b>0</b> · 👥 Рефералов: <b>{invited_count}</b>\n\n"
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
    "promo_discount_requires_purchase": (
        "🎟 <b>Это промокод на скидку.</b>\n"
        "Чтобы применить его, начните оформление подписки в каталоге — "
        "ввести промокод можно будет на этапе выбора длительности."
    ),
    # ---- Stage 3: referral ----------------------------------------------
    "referral_program_screen": (
        "🎁 <b>Реферальная программа</b>\n\n"
        "Приглашайте друзей и получайте <b>100 ₽</b> на баланс за каждого, "
        "кто оформит подписку!\n"
        "Друзья получат скидку <b>10%</b> на первую покупку.\n\n"
        "Ваша ссылка:\n<code>{ref_link}</code>\n\n"
        "Приглашено: <b>{invited}</b>\n"
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


# Hardcoded fallbacks for inline-button labels (Stage 6). These mirror the
# original literal strings in ``app/keyboards/*.py`` so a backend outage
# during cold start still gives a usable UI. Keep in sync with the seed
# block in alembic migration ``0008_text_kind_and_icon`` — the migration
# loads the same labels into the database on first deploy.
_BUTTON_FALLBACKS: dict[str, str] = {
    "btn.main_menu.catalog": "Каталог",
    "btn.main_menu.profile": "Профиль",
    "btn.main_menu.support": "Поддержка",
    "btn.main_menu.promo": "Промокод",
    "btn.main_menu.idea": "Предложить идею",
    "btn.main_menu.about": "О проекте",
    "btn.common.back": "← Назад",
    "btn.common.to_menu": "🏠 В меню",
    "btn.common.subscribe": "Подписаться",
    "btn.common.subscribed": "Я подписался ✅",
    "btn.profile.add_more": "➕ Оформить ещё",
    "btn.profile.topup": "💰 Пополнить баланс",
    "btn.profile.referral": "🎁 Реферальная программа",
    "btn.referral.share": "📤 Поделиться",
    "btn.subscription.howto": "📖 Как подключиться",
    "btn.subscription.extend": "♻️ Продлить",
    "btn.payment.sbp": "СБП",
    "btn.payment.cryptobot": "CryptoBot",
    "btn.payment.crypto": "Криптовалюта",
    "btn.payment.balance": "💰 Баланс",
    "btn.payment.balance_locked": "🔒 Баланс",
    "btn.payment.pay": "💳 Оплатить",
    "btn.payment.cancel": "← Отменить",
    "btn.ticket.create_support": "Создать тикет",
    "btn.ticket.create_idea": "Предложить идею",
    "btn.ticket.close_yes": "Да, закрыть",
    "btn.ticket.close_no": "Отмена",
    "btn.promo.skip": "Нет промокода",
    "btn.promo.retry": "✏️ Ввести другой",
    "btn.promo.skip_alt": "Без промокода",
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
            cache: dict[str, TextEntry] = {}
            for key, item in raw.items():
                kind = item.get("kind") or "message"
                value_html = item.get("value_html") or ""
                # Normalize message bodies: TipTap emits ``<p>`` paragraphs
                # and may double-escape ``<tg-emoji>`` snippets; Telegram's
                # HTML parser rejects both. Buttons are plain labels — no
                # tags to normalize.
                if kind == "message" and value_html:
                    value_html = _normalize_message_html(value_html)
                cache[key] = TextEntry(
                    value_html=value_html,
                    media_file_id=item.get("media_file_id"),
                    media_kind=item.get("media_kind"),
                    kind=kind,
                    icon_custom_emoji_id=item.get("icon_custom_emoji_id"),
                    url=item.get("url"),
                )
            self._cache = cache
            self._expires_at = now + self._ttl
            log.debug("texts.refreshed", count=len(self._cache))

    def _resolve(self, key: str) -> TextEntry | None:
        entry = self._cache.get(key)
        if entry is not None:
            return entry
        fallback = _HARDCODED_FALLBACKS.get(key)
        if fallback is not None:
            return TextEntry(value_html=fallback)
        button_fallback = _BUTTON_FALLBACKS.get(key)
        if button_fallback is not None:
            return TextEntry(value_html=button_fallback, kind="button")
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
            kind=entry.kind,
            icon_custom_emoji_id=entry.icon_custom_emoji_id,
            url=entry.url,
        )

    async def get_button(
        self, key: str, /, **kwargs: object
    ) -> tuple[str, str | None]:
        """Return ``(label, icon_custom_emoji_id)`` for an inline-button key.

        Behaviour:

        - cache hit / fallback hit: the label is rendered through ``str.format``
          (so callers can parameterise things like a price or counter) and
          the optional premium-emoji document id is returned alongside.
        - miss: the bot still has to render *something*, so we return a loud
          ``"???"`` placeholder rather than a Python exception. Missing keys
          surface in the bot logs via ``texts.missing_key`` for triage.

        Telegram's ``InlineKeyboardButton.text`` is plain text — no HTML, no
        entities, no formatting. Custom emoji on the button can only be set
        via the separate ``icon_custom_emoji_id`` field (Bot API ≥ 7.x), so
        operators who want a premium emoji on a button paste the emoji's
        document id into the admin editor and we forward it here.
        """
        if time.monotonic() >= self._expires_at or key not in self._cache:
            await self._refresh()

        entry = self._resolve(key)
        if entry is None:
            log.warning("texts.missing_key", key=key)
            return ("???", None)
        label = self._format(entry.value_html, **kwargs) if kwargs else entry.value_html
        return (label, entry.icon_custom_emoji_id)

    async def get_url_button(
        self, key: str, /, **kwargs: object
    ) -> tuple[str, str | None, str | None]:
        """Return ``(label, icon_custom_emoji_id, url)`` for a button key.

        Same lookup as :meth:`get_button` but also surfaces the optional
        outbound URL stored on the text row. Callers decide what to do when
        ``url`` is ``None`` (typically: render as a callback button instead).
        Missing keys log a warning and return ``("???", None, None)``.
        """
        if time.monotonic() >= self._expires_at or key not in self._cache:
            await self._refresh()

        entry = self._resolve(key)
        if entry is None:
            log.warning("texts.missing_key", key=key)
            return ("???", None, None)
        label = self._format(entry.value_html, **kwargs) if kwargs else entry.value_html
        return (label, entry.icon_custom_emoji_id, entry.url)

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
