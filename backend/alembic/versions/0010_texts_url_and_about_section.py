"""Add ``texts.url`` column and seed the «О проекте» (about) section.

Two changes ship together because they're naturally coupled:

1. Add a nullable ``texts.url`` column. Currently button rows
   (``kind='button'``) only store a label; this lets admins also attach an
   outbound URL so the bot can render a URL button instead of a callback
   button. ``message`` rows ignore the column.

2. Seed the «О проекте» section so the previously-stub callback
   ``about`` becomes a real screen out of the box:
   - ``about`` (kind=message) — body text, edited via TipTap.
   - ``btn.about.privacy`` (kind=button, url=…) — link to /privacy SPA page.
   - ``btn.about.terms`` (kind=button, url=…) — link to /terms.
   - ``btn.about.channel`` (kind=button, url=…) — link to the project channel.

All inserts are ``ON CONFLICT (key) DO NOTHING`` so re-applying on
environments where these rows were created manually is a no-op.

Revision ID: 0010_texts_url_and_about_section
Revises: 0009_add_key_issuing_text
Create Date: 2026-05-06 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010_texts_url_and_about_section"
down_revision: str | None = "0009_add_key_issuing_text"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_ABOUT_BODY_HTML = (
    "<b>О проекте</b>\n\n"
    "<b>PIX VPN</b> — быстрый и стабильный VPN для повседневного "
    "использования. Мы предоставляем доступ к серверам по всему миру, "
    "поддерживаем все популярные клиенты (iOS, Android, Windows, macOS, "
    "Linux) и работаем без логов.\n\n"
    "Если возникли вопросы — напиши в раздел «Поддержка» в главном меню."
)

_ABOUT_BODY_DESCRIPTION = (
    "Текст раздела «О проекте» в главном меню. Под ним — кнопки "
    "btn.about.privacy / btn.about.terms / btn.about.channel."
)

# (key, label, description, url)
_ABOUT_BUTTONS: list[tuple[str, str, str, str]] = [
    (
        "btn.about.privacy",
        "Политика конфиденциальности",
        "О проекте → ссылка на /privacy",
        "https://pix-app.xyz/privacy",
    ),
    (
        "btn.about.terms",
        "Пользовательское соглашение",
        "О проекте → ссылка на /terms",
        "https://pix-app.xyz/terms",
    ),
    (
        "btn.about.channel",
        "Наш канал",
        "О проекте → ссылка на Telegram-канал проекта",
        "https://t.me/pix_vpn_app",
    ),
]


def upgrade() -> None:
    # 1. New column. Nullable to keep existing rows untouched; only button
    #    rows ever set it. 512 chars is enough for any reasonable URL with
    #    query string and headroom.
    op.add_column(
        "texts",
        sa.Column("url", sa.String(length=512), nullable=True),
    )

    bind = op.get_bind()

    # 2a. Seed the message body. ``ON CONFLICT (key) DO NOTHING`` — if an
    #     admin already wrote their own «О проекте» text in the DB before
    #     this migration ran, leave it alone.
    bind.execute(
        sa.text(
            """
            INSERT INTO texts (key, value_html, description, kind, updated_at)
            VALUES (:key, :value_html, :description, 'message', NOW())
            ON CONFLICT (key) DO NOTHING
            """
        ),
        {
            "key": "about",
            "value_html": _ABOUT_BODY_HTML,
            "description": _ABOUT_BODY_DESCRIPTION,
        },
    )

    # 2b. Seed the three URL buttons.
    for key, label, description, url in _ABOUT_BUTTONS:
        bind.execute(
            sa.text(
                """
                INSERT INTO texts (
                    key, value_html, description, kind, url, updated_at
                )
                VALUES (
                    :key, :value_html, :description, 'button', :url, NOW()
                )
                ON CONFLICT (key) DO NOTHING
                """
            ),
            {
                "key": key,
                "value_html": label,
                "description": description,
                "url": url,
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    keys = ["about", *[k for k, _, _, _ in _ABOUT_BUTTONS]]
    bind.execute(
        sa.text("DELETE FROM texts WHERE key = ANY(:keys)"),
        {"keys": keys},
    )
    op.drop_column("texts", "url")
