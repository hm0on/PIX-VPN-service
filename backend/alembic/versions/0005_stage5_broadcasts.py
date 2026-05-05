"""Stage 5 schema: broadcasts + broadcast_recipients

Revision ID: 0005_stage5_broadcasts
Revises: 0004_stage4
Create Date: 2026-05-05 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0005_stage5_broadcasts"
down_revision: str | None = "0004_stage4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json_type():
    return sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    # broadcasts
    op.create_table(
        "broadcasts",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("html_text", sa.Text(), nullable=False),
        sa.Column("photo_file_id", sa.String(length=255), nullable=True),
        sa.Column("photo_path", sa.String(length=512), nullable=True),
        sa.Column("buttons", _json_type(), nullable=True),
        sa.Column(
            "target",
            sa.String(length=32),
            nullable=False,
            server_default="all",
        ),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="draft",
        ),
        sa.Column(
            "recipients_total",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("sent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("created_by_admin_key_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_by_admin_key_label", sa.String(length=64), nullable=True
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["created_by_admin_key_id"],
            ["admin_keys.id"],
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_broadcasts_status", "broadcasts", ["status"])
    op.create_index(
        "ix_broadcasts_scheduled_at", "broadcasts", ["scheduled_at"]
    )
    op.create_index(
        "ix_broadcasts_created_at_desc", "broadcasts", ["created_at"]
    )

    # broadcast_recipients
    op.create_table(
        "broadcast_recipients",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("broadcast_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["broadcast_id"], ["broadcasts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_broadcast_recipients_broadcast_status",
        "broadcast_recipients",
        ["broadcast_id", "status"],
    )
    op.create_index(
        "ix_broadcast_recipients_user_id",
        "broadcast_recipients",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_broadcast_recipients_user_id", table_name="broadcast_recipients"
    )
    op.drop_index(
        "ix_broadcast_recipients_broadcast_status",
        table_name="broadcast_recipients",
    )
    op.drop_table("broadcast_recipients")

    op.drop_index("ix_broadcasts_created_at_desc", table_name="broadcasts")
    op.drop_index("ix_broadcasts_scheduled_at", table_name="broadcasts")
    op.drop_index("ix_broadcasts_status", table_name="broadcasts")
    op.drop_table("broadcasts")
