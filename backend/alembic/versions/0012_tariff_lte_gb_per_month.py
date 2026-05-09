"""Add ``lte_gb_per_month`` column to tariffs.

Each subscription issued through NorthLine carries an optional LTE add-on
(``lte_gb`` in ``POST /keys``). Up to now we never sent it, so the
provider treated all keys as «no LTE». Product decision: every public
tariff bundles 35GB of LTE; custom tariffs (unlimited etc.) will set
their own value later. We persist the value per-tariff so changing the
bundle size is a DB tweak rather than a code deploy.

The column is ``NOT NULL`` with ``DEFAULT 35`` — existing rows get 35
without any data migration. ``downgrade`` drops the column.

Revision ID: 0012_tariff_lte_gb_per_month
Revises: 0011_referral_share_button
Create Date: 2026-05-09 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012_tariff_lte_gb_per_month"
down_revision: str | None = "0011_referral_share_button"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tariffs",
        sa.Column(
            "lte_gb_per_month",
            sa.Integer(),
            nullable=False,
            server_default="35",
        ),
    )


def downgrade() -> None:
    op.drop_column("tariffs", "lte_gb_per_month")
