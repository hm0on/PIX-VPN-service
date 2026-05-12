"""Fix ``promo_discount_applied`` placeholder + reduce FREE tariff config.

Two unrelated production-data fixes shipped together:

1. ``promo_discount_applied`` text row used to contain ``{total}`` but every
   call site in the bot (catalog/profile handlers) passes ``amount=``,
   leaving the raw ``{total}`` placeholder in the rendered message. Switch
   the value to ``{amount}`` so ``str.format`` substitutes correctly.

2. FREE tariff (``code='free'``) should issue keys without the 35 GB LTE
   add-on we hand to paid tariffs by default. Set ``lte_gb_per_month=0``
   on that row so ``NorthLineClient.create_key`` skips the ``lte_gb`` body
   field for trial keys (see ``free_trial_service`` and ``payment_service``).

Both updates are conditional (`WHERE` filters limit to the affected rows)
and idempotent — re-running the migration is a no-op once the values
match. ``downgrade()`` flips the same fields back to their previous
values so the migration stays reversible.

Revision ID: 0014_fix_promo_text_free_tariff
Revises: 0013_purge_legacy_promo_outbox
Create Date: 2026-05-10 00:00:00.000000

NOTE: revision id kept short because ``alembic_version.version_num`` is
``VARCHAR(32)`` and the auto-generated longer name overflowed in prod.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0014_fix_promo_text_free_tariff"
down_revision: str | None = "0013_purge_legacy_promo_outbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_PROMO_KEY = "promo_discount_applied"


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Fix the placeholder in the existing promo text row. Admins may
    #    have customised the surrounding HTML (premium emoji, etc.), so
    #    we surgically swap ``{total}`` → ``{amount}`` rather than
    #    rewriting the whole row. ``replace`` is idempotent — once the
    #    placeholder is already ``{amount}`` the UPDATE is a no-op.
    bind.execute(
        sa.text(
            """
            UPDATE texts
               SET value_html = REPLACE(value_html, '{total}', '{amount}'),
                   updated_at = NOW()
             WHERE key = :key
               AND value_html LIKE '%{total}%'
            """
        ),
        {"key": _PROMO_KEY},
    )

    # 2. Zero out LTE for the FREE tariff so the trial key matches the
    #    "no LTE add-on" config ops asked for. Only touches the row when
    #    the column still carries the legacy default (35) — preserves any
    #    manual override an admin may have set in the meantime.
    bind.execute(
        sa.text(
            """
            UPDATE tariffs
               SET lte_gb_per_month = 0
             WHERE code = 'free'
               AND lte_gb_per_month <> 0
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()

    bind.execute(
        sa.text(
            """
            UPDATE texts
               SET value_html = REPLACE(value_html, '{amount}', '{total}'),
                   updated_at = NOW()
             WHERE key = :key
               AND value_html LIKE '%{amount}%'
            """
        ),
        {"key": _PROMO_KEY},
    )

    bind.execute(
        sa.text(
            """
            UPDATE tariffs
               SET lte_gb_per_month = 35
             WHERE code = 'free'
               AND lte_gb_per_month = 0
            """
        )
    )
