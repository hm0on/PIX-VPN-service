"""Add buttons_per_row to broadcasts.

Stage 5 polish: the admin UI lets editors pack inline buttons N-per-row, but
that knob was previously kept only in component state and lost on reload.
Persist it on the broadcast row so the worker can build the same layout the
editor previewed.

Revision ID: 0007_broadcast_buttons_per_row
Revises: 0006_texts_media
Create Date: 2026-05-06 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007_broadcast_buttons_per_row"
down_revision: str | None = "0006_texts_media"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "broadcasts",
        sa.Column(
            "buttons_per_row",
            sa.SmallInteger(),
            nullable=False,
            server_default="1",
        ),
    )


def downgrade() -> None:
    op.drop_column("broadcasts", "buttons_per_row")
