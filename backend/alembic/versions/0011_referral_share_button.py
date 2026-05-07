"""Seed the «Поделиться» button on the Referral Program screen.

The referral screen renders a Telegram ``switch_inline_query`` button so the
user can pick a chat and send their referral link with a pre-filled pitch.
Up to now the button label was hardcoded in the bot; this migration makes it
admin-editable like the rest of the inline-button labels — the bot picks the
label up via ``TextService.get_button("btn.referral.share")``.

The row uses ``kind='button'`` and leaves ``url`` empty (the action is
``switch_inline_query``, not a URL or a callback). ``icon_custom_emoji_id``
remains optional so an admin can attach a premium emoji from the admin UI.

Idempotent: ``ON CONFLICT (key) DO NOTHING`` — re-running on environments
where someone created the row by hand is a no-op.

Revision ID: 0011_referral_share_button
Revises: 0010_texts_url_and_about_section
Create Date: 2026-05-07 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011_referral_share_button"
down_revision: str | None = "0010_texts_url_and_about_section"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_KEY = "btn.referral.share"
_LABEL = "📤 Поделиться"
_DESCRIPTION = (
    "Профиль → Реферальная программа → кнопка «Поделиться». "
    "Открывает выбор чата (switch_inline_query) с готовым сообщением и "
    "реферальной ссылкой."
)


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            INSERT INTO texts (key, value_html, description, kind, updated_at)
            VALUES (:key, :value_html, :description, 'button', NOW())
            ON CONFLICT (key) DO NOTHING
            """
        ),
        {"key": _KEY, "value_html": _LABEL, "description": _DESCRIPTION},
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text("DELETE FROM texts WHERE key = :key"),
        {"key": _KEY},
    )
