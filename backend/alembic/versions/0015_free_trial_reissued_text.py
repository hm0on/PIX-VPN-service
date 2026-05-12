"""Seed ``free_trial_reissued`` text used by the one-shot FREE-reissue script.

Background: we reduced the FREE tariff config (1 device, 0 GB LTE) in
migration 0014 and want to retroactively re-issue keys for the 9
in-flight trial subscriptions so they match the new shape. The one-shot
``scripts/reissue_free_trials.py`` posts to the outbox with this text
key; if the row didn't exist the worker would render
``<i>[text:free_trial_reissued not found]</i>``.

Idempotent ``INSERT ... ON CONFLICT DO NOTHING`` so admins who already
seeded the row (e.g. via the admin panel) keep their customised wording.

Revision ID: 0015_free_trial_reissued_text
Revises: 0014_fix_promo_text_free_tariff
Create Date: 2026-05-12 18:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0015_free_trial_reissued_text"
down_revision: str | None = "0014_fix_promo_text_free_tariff"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_KEY = "free_trial_reissued"
_VALUE_HTML = (
    "🎁 <b>Ваш FREE-ключ обновлён</b>\n\n"
    "Мы изменили конфигурацию бесплатного тарифа и перевыпустили "
    "ваш ключ. Старый ключ больше не работает — используйте новый:\n\n"
    "<code>{key_url}</code>\n\n"
    "Действует 3 дня."
)
_DESCRIPTION = (
    "Уведомление при разовой массовой перевыдаче FREE-ключей "
    "после смены конфигурации тарифа (1 устройство, без LTE)."
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
