"""Seed the ``key_issuing`` text row used between «Pay with balance» click and key delivery.

Background: balance-paid purchases now show a single chat message that the
bot edits twice — first to "⏳ Выдаём ключ..." (this key), then to the
final "✅ ... заказ #N\\n\\nВаш ключ: ..." once NorthLine returns. The
new text is admin-editable like every other message; this migration just
inserts the row into existing databases. Fresh deploys get it from
``backend/app/seeds.py`` instead — both stay in sync.

Idempotent insert (``ON CONFLICT (key) DO NOTHING``) so re-applying the
migration on a database where the key was created manually is a no-op.

Revision ID: 0009_add_key_issuing_text
Revises: 0008_text_kind_and_icon
Create Date: 2026-05-06 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009_add_key_issuing_text"
down_revision: str | None = "0008_text_kind_and_icon"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_KEY = "key_issuing"
_VALUE_HTML = "⏳ <b>Выдаём ключ...</b>"
_DESCRIPTION = (
    "Промежуточное сообщение, которое бот показывает между нажатием "
    "«Оплатить с баланса» и фактической выдачей ключа (пока NorthLine "
    "провижинит подписку, ~1-3 сек)."
)


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            INSERT INTO texts (key, value_html, description, kind, updated_at)
            VALUES (:key, :value_html, :description, 'message', NOW())
            ON CONFLICT (key) DO NOTHING
            """
        ),
        {
            "key": _KEY,
            "value_html": _VALUE_HTML,
            "description": _DESCRIPTION,
        },
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text("DELETE FROM texts WHERE key = :key"),
        {"key": _KEY},
    )
