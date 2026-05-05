"""Add media_file_id / media_kind to texts

Revision ID: 0006_texts_media
Revises: 0005_stage5_broadcasts
Create Date: 2026-05-05 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006_texts_media"
down_revision: str | None = "0005_stage5_broadcasts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "texts",
        sa.Column("media_file_id", sa.String(length=256), nullable=True),
    )
    op.add_column(
        "texts",
        # photo | video | animation. Validated on the API layer.
        sa.Column("media_kind", sa.String(length=16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("texts", "media_kind")
    op.drop_column("texts", "media_file_id")
