"""Conversion pack: trial 5d/2dev/50GB, personal promo codes, ref-trial bonus.

Three independent nullable column additions to land the pack:

1. ``tariffs.traffic_gb_per_month`` — declarative traffic quota per tariff.
   NorthLine does not currently accept a separate "regular traffic" limit
   (only ``unlimited_traffic`` and ``lte_gb``), so the value lives on our
   side and is rendered into tariff descriptions / FREE-trial UX copy.
   Nullable because pre-existing paid tariffs have no declared quota.

2. ``promo_codes.user_id`` — when non-NULL, the promo can only be applied
   by that specific user. Lets us mint per-user discount codes (e.g. the
   24h trial-expiring nudge, the referrer's bonus on a referee's trial)
   instead of inventing a parallel "personal promo" table. A partial
   index ``WHERE user_id IS NOT NULL`` keeps the common case (global
   promos with user_id=NULL) untouched.

3. ``referrals.trial_bonus_issued_at`` — guards against issuing the
   referrer's trial-bonus promo more than once per (referrer, referee)
   pair. Separate from ``bonus_paid`` because trial-bonus and paid-bonus
   are independent (referee can earn both).

All columns are NULLable / no backfill needed → safe online add.

Revision ID: 0016_conversion_pack
Revises: 0015_free_trial_reissued_text
Create Date: 2026-05-13 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0016_conversion_pack"
down_revision: str | None = "0015_free_trial_reissued_text"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tariffs",
        sa.Column("traffic_gb_per_month", sa.Integer(), nullable=True),
    )

    op.add_column(
        "promo_codes",
        sa.Column("user_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_promo_codes_user_id_users",
        "promo_codes",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    # Partial index — only personal promos are looked up by user_id;
    # global promos (user_id=NULL) don't bloat the index.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_promo_codes_user_id "
        "ON promo_codes (user_id) WHERE user_id IS NOT NULL"
    )

    op.add_column(
        "referrals",
        sa.Column(
            "trial_bonus_issued_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("referrals", "trial_bonus_issued_at")
    op.execute("DROP INDEX IF EXISTS ix_promo_codes_user_id")
    op.drop_constraint("fk_promo_codes_user_id_users", "promo_codes", type_="foreignkey")
    op.drop_column("promo_codes", "user_id")
    op.drop_column("tariffs", "traffic_gb_per_month")
