"""Purge leftover ``promo_balance_applied`` outbox rows.

The previous round of the duplicate-promo-message fix removed the
``outbox_service.enqueue_message`` call from ``PromoService._apply_balance``
so that the bot becomes the single source of the «Промокод применён»
notification (it renders it synchronously from the HTTP response). What
that fix did NOT do was drain the rows that had already been enqueued
before the deploy. The outbox dispatcher kept picking them up and the
user therefore still received two messages for any promo applied around
the deploy boundary.

This migration is a one-shot cleanup: mark every still-pending
``promo_balance_applied`` row as ``failed`` with an explanatory
``last_error``. ``failed`` (vs deleting) keeps the row for auditing
without scheduling another delivery. Idempotent: re-running matches no
rows because the WHERE clause requires ``status='pending'``.

Rows that were already ``sent`` are left alone — they were delivered
correctly when the user wasn't yet reading both responses.

Revision ID: 0013_purge_legacy_promo_outbox
Revises: 0012_tariff_lte_gb_per_month
Create Date: 2026-05-10 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0013_purge_legacy_promo_outbox"
down_revision: str | None = "0012_tariff_lte_gb_per_month"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    # JSON path differs between Postgres (->>) and SQLite (json_extract).
    # Tests run on SQLite; production is Postgres. Both shapes are covered.
    if dialect == "postgresql":
        op.execute(
            """
            UPDATE outbox
            SET status = 'failed',
                last_error = 'purged: legacy promo_balance_applied (round-2 fix)'
            WHERE status = 'pending'
              AND payload ->> 'text_key' = 'promo_balance_applied'
            """
        )
    else:
        op.execute(
            """
            UPDATE outbox
            SET status = 'failed',
                last_error = 'purged: legacy promo_balance_applied (round-2 fix)'
            WHERE status = 'pending'
              AND json_extract(payload, '$.text_key') = 'promo_balance_applied'
            """
        )


def downgrade() -> None:
    # Intentionally a no-op: we'd be reviving a known-buggy delivery.
    # Operators who need to reverse this can do so manually with a
    # targeted UPDATE on the affected rows.
    pass
