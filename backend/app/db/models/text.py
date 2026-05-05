"""Text (HTML content) ORM model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text as SAText, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IntPK


class Text(IntPK, Base):
    __tablename__ = "texts"

    key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    value_html: Mapped[str] = mapped_column(SAText, nullable=False)
    description: Mapped[str | None] = mapped_column(SAText, nullable=True)

    # Optional Telegram media attachment. ``media_file_id`` is the bot-scoped
    # file_id obtained by sending a photo/video/animation to the bot once and
    # capturing the id from the resulting Message (see /getfileid command in
    # the support group). ``media_kind`` ∈ {"photo", "video", "animation"}.
    media_file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    media_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # Discriminator: ``"message"`` (default) — ``value_html`` is rich HTML
    # rendered into a Telegram message and edited via TipTap in the admin UI.
    # ``"button"`` — ``value_html`` is the plain label string of an inline
    # keyboard button (Telegram does not allow HTML or entities in
    # ``InlineKeyboardButton.text``), and ``icon_custom_emoji_id`` may carry
    # a Telegram custom-emoji document id for the optional premium-emoji icon
    # rendered to the left of the label.
    kind: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="message"
    )
    icon_custom_emoji_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    updated_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
