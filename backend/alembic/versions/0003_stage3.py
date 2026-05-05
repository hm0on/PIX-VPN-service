"""Stage 3 schema: promo_codes, promo_activations, referrals, notifications_sent

Revision ID: 0003_stage3
Revises: 0002_stage2
Create Date: 2026-05-04 00:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_stage3"
down_revision: Union[str, None] = "0002_stage2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _code_type() -> sa.types.TypeEngine:
    """CITEXT on Postgres, plain VARCHAR(64) elsewhere (e.g. SQLite tests)."""
    return sa.String(length=64).with_variant(postgresql.CITEXT(), "postgresql")


def upgrade() -> None:
    # promo_codes
    op.create_table(
        "promo_codes",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("code", _code_type(), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False),
        sa.Column("max_total_activations", sa.Integer(), nullable=True),
        sa.Column(
            "max_per_user",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
        sa.Column(
            "current_activations",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_by_admin_key_label", sa.String(length=64), nullable=True
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.UniqueConstraint("code", name="uq_promo_codes_code"),
    )
    op.create_index("ix_promo_codes_code", "promo_codes", ["code"])
    op.create_index("ix_promo_codes_is_active", "promo_codes", ["is_active"])
    op.create_index("ix_promo_codes_valid_until", "promo_codes", ["valid_until"])

    # promo_activations
    op.create_table(
        "promo_activations",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("promo_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("payment_id", sa.BigInteger(), nullable=True),
        sa.Column("amount_applied_kopecks", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["promo_id"], ["promo_codes.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["payment_id"], ["payments.id"], ondelete="SET NULL"
        ),
    )
    op.create_index(
        "ix_promo_activations_promo_id", "promo_activations", ["promo_id"]
    )
    op.create_index(
        "ix_promo_activations_user_id", "promo_activations", ["user_id"]
    )

    # referrals
    op.create_table(
        "referrals",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("referrer_id", sa.BigInteger(), nullable=False),
        sa.Column("referee_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "bonus_paid",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("bonus_paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "referee_first_purchase_id", sa.BigInteger(), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["referrer_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["referee_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["referee_first_purchase_id"], ["payments.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint("referee_id", name="uq_referrals_referee_id"),
    )
    op.create_index("ix_referrals_referrer_id", "referrals", ["referrer_id"])
    op.create_index("ix_referrals_referee_id", "referrals", ["referee_id"])

    # notifications_sent
    op.create_table(
        "notifications_sent",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("subscription_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["subscription_id"], ["subscriptions.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "subscription_id", "kind", name="uq_notifications_sent_sub_kind"
        ),
    )
    op.create_index(
        "ix_notifications_sent_user_id", "notifications_sent", ["user_id"]
    )
    op.create_index(
        "ix_notifications_sent_subscription_id",
        "notifications_sent",
        ["subscription_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_notifications_sent_subscription_id", table_name="notifications_sent"
    )
    op.drop_index(
        "ix_notifications_sent_user_id", table_name="notifications_sent"
    )
    op.drop_table("notifications_sent")

    op.drop_index("ix_referrals_referee_id", table_name="referrals")
    op.drop_index("ix_referrals_referrer_id", table_name="referrals")
    op.drop_table("referrals")

    op.drop_index("ix_promo_activations_user_id", table_name="promo_activations")
    op.drop_index("ix_promo_activations_promo_id", table_name="promo_activations")
    op.drop_table("promo_activations")

    op.drop_index("ix_promo_codes_valid_until", table_name="promo_codes")
    op.drop_index("ix_promo_codes_is_active", table_name="promo_codes")
    op.drop_index("ix_promo_codes_code", table_name="promo_codes")
    op.drop_table("promo_codes")
