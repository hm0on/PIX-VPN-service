"""``/getfileid`` helper for the support group.

When the operator wants to attach an image / video / animation to a bot
text (via the admin panel), they need a Telegram ``file_id``. The simplest
way to capture one is:

1. In the **support group**, in the **General topic** (no thread), send
   (or forward) the desired media file as a reply to ``/getfileid`` —
   or just send it with the caption ``/getfileid``.
2. The bot replies with the ``file_id`` and detected ``kind`` so it can be
   pasted into the corresponding text in the admin panel.

The router is intentionally narrow:
- only fires inside ``SUPPORT_GROUP_ID``;
- only in the General topic (``message_thread_id is None``) so it does not
  collide with ticket topics handled by :mod:`handlers.support_admin`;
- only on photo / video / animation / document / sticker — anything else is
  ignored.

We do NOT require the user to be admin: whoever has access to the support
group is trusted (they already see all tickets).
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from app.config import Settings
from app.utils.logging import get_logger

router = Router(name="getfileid")
log = get_logger("bot.handlers.getfileid")


def _in_support_general_topic(message: Message, settings: Settings) -> bool:
    """Filter: support group + General topic only."""
    if settings.SUPPORT_GROUP_ID is None:
        return False
    if message.chat.id != settings.SUPPORT_GROUP_ID:
        return False
    # General topic in a forum supergroup has no thread (or thread_id == 1
    # depending on Telegram version; both arrive as ``None`` for a "regular"
    # message). Ticket topics always carry a non-None ``message_thread_id``.
    if message.message_thread_id is not None and message.message_thread_id != 1:
        return False
    return True


def _extract_file_id_and_kind(msg: Message) -> tuple[str, str] | None:
    """Return ``(file_id, kind)`` for any supported media on ``msg``.

    Photo: largest size. Video / animation / document / sticker: as is.
    Returns ``None`` when no recognizable media is attached.
    """
    if msg.photo:
        # Telegram returns multiple sizes — the last one is the largest.
        return msg.photo[-1].file_id, "photo"
    if msg.animation:
        return msg.animation.file_id, "animation"
    if msg.video:
        return msg.video.file_id, "video"
    if msg.document:
        # We don't (yet) support `document` in send_text_or_media — surface
        # it anyway in case the operator wants the id for something else.
        return msg.document.file_id, "document"
    if msg.sticker:
        return msg.sticker.file_id, "sticker"
    return None


@router.message(Command("getfileid"))
async def cmd_getfileid(message: Message, settings: Settings) -> None:
    """Reply with the ``file_id`` of the attached or replied-to media."""
    if not _in_support_general_topic(message, settings):
        return

    # Source of media: either the same message (caption-style) or a reply.
    candidate = message.reply_to_message or message
    extracted = _extract_file_id_and_kind(candidate)

    if extracted is None:
        await message.reply(
            "Прикрепите фото / видео / GIF к этому сообщению "
            "(или ответьте этой командой на сообщение с медиа), "
            "и я верну <code>file_id</code>."
        )
        return

    file_id, kind = extracted
    if kind in {"document", "sticker"}:
        note = (
            f"\n\n<i>⚠️ Тип <b>{kind}</b> не поддерживается в "
            f"<code>send_text_or_media</code>. Используйте photo/video/animation.</i>"
        )
    else:
        note = ""

    await message.reply(
        f"<b>kind:</b> <code>{kind}</code>\n"
        f"<b>file_id:</b>\n<code>{file_id}</code>"
        f"{note}\n\n"
        "Скопируйте <code>file_id</code> и вставьте в админке "
        "(Тексты бота → выберите ключ → поле «file_id», kind → "
        f"<code>{kind if kind in {'photo', 'video', 'animation'} else 'photo'}</code>)."
    )
    log.info("getfileid.replied", kind=kind, chat_id=message.chat.id)


# Convenience: bare media (no command) in the General topic also gets a hint
# to use /getfileid — saves a confused operator a round-trip. Triggers only
# when the message has media AND no command (so it doesn't double-fire with
# /getfileid above).
@router.message(F.photo | F.animation | F.video)
async def hint_on_bare_media(message: Message, settings: Settings) -> None:
    if not _in_support_general_topic(message, settings):
        return
    # If the caption is empty or doesn't contain /getfileid, nudge the operator.
    caption = (message.caption or "").lower()
    if "/getfileid" in caption:
        # Already handled by cmd_getfileid via Command filter — bail.
        return

    extracted = _extract_file_id_and_kind(message)
    if extracted is None:
        return
    file_id, kind = extracted
    await message.reply(
        f"<b>kind:</b> <code>{kind}</code>\n"
        f"<b>file_id:</b>\n<code>{file_id}</code>\n\n"
        "Подсказка: ответьте /getfileid любому медиа, чтобы получить тот же ответ."
    )
