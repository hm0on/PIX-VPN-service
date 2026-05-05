"""Stage 2 schema: subscriptions, payments, balance_transactions, outbox, idempotency_keys

Revision ID: 0002_stage2
Revises: 0001_initial_stage1
Create Date: 2026-05-04 23:30:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_stage2"
down_revision: Union[str, None] = "0001_initial_stage1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # subscriptions
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("tariff_id", sa.Integer(), nullable=False),
        sa.Column("tariff_duration_id", sa.Integer(), nullable=True),
        sa.Column("provider_subscription_id", sa.String(length=128), nullable=True),
        sa.Column("key_url", sa.Text(), nullable=True),
        sa.Column("devices", sa.Integer(), nullable=False),
        sa.Column("days", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deactivation_reason", sa.Text(), nullable=True),
        sa.Column(
            "is_free_trial",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tariff_id"], ["tariffs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["tariff_duration_id"], ["tariff_durations.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint(
            "provider_subscription_id", name="uq_subscriptions_provider_subscription_id"
        ),
    )
    op.create_index("ix_subscriptions_user_id", "subscriptions", ["user_id"])
    op.create_index("ix_subscriptions_status", "subscriptions", ["status"])
    op.create_index("ix_subscriptions_expires_at", "subscriptions", ["expires_at"])
    op.create_index(
        "ix_subscriptions_user_free_trial",
        "subscriptions",
        ["user_id", "is_free_trial"],
    )

    # payments
    op.create_table(
        "payments",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("subscription_id", sa.BigInteger(), nullable=True),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.String(length=128), nullable=True),
        sa.Column("amount_kopecks", sa.BigInteger(), nullable=False),
        sa.Column(
            "currency", sa.String(length=8), server_default="RUB", nullable=False
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["subscription_id"], ["subscriptions.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint("external_id", name="uq_payments_external_id"),
    )
    op.create_index("ix_payments_user_id", "payments", ["user_id"])
    op.create_index("ix_payments_status", "payments", ["status"])
    op.create_index("ix_payments_external_id", "payments", ["external_id"])
    op.create_index("ix_payments_created_at_desc", "payments", ["created_at"])
    op.create_index(
        "ix_payments_meta_gin", "payments", ["meta"], postgresql_using="gin"
    )

    # balance_transactions
    op.create_table(
        "balance_transactions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("amount_kopecks", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.Column("ref_payment_id", sa.BigInteger(), nullable=True),
        sa.Column("ref_subscription_id", sa.BigInteger(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("balance_after_kopecks", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["ref_payment_id"], ["payments.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["ref_subscription_id"], ["subscriptions.id"], ondelete="SET NULL"
        ),
    )
    op.create_index(
        "ix_balance_transactions_user_id", "balance_transactions", ["user_id"]
    )
    op.create_index(
        "ix_balance_transactions_reason", "balance_transactions", ["reason"]
    )
    op.create_index(
        "ix_balance_transactions_created_at_desc",
        "balance_transactions",
        ["created_at"],
    )

    # outbox
    op.create_table(
        "outbox",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "message_type",
            sa.String(length=16),
            server_default="text",
            nullable=False,
        ),
        sa.Column(
            "payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "send_after",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_outbox_status", "outbox", ["status"])
    op.create_index("ix_outbox_send_after", "outbox", ["send_after"])
    op.create_index(
        "ix_outbox_status_send_after", "outbox", ["status", "send_after"]
    )

    # idempotency_keys
    op.create_table(
        "idempotency_keys",
        sa.Column("key", sa.String(length=64), primary_key=True),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column(
            "response", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_idempotency_keys_created_at",
        "idempotency_keys",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_idempotency_keys_created_at", table_name="idempotency_keys")
    op.drop_table("idempotency_keys")

    op.drop_index("ix_outbox_status_send_after", table_name="outbox")
    op.drop_index("ix_outbox_send_after", table_name="outbox")
    op.drop_index("ix_outbox_status", table_name="outbox")
    op.drop_table("outbox")

    op.drop_index(
        "ix_balance_transactions_created_at_desc", table_name="balance_transactions"
    )
    op.drop_index(
        "ix_balance_transactions_reason", table_name="balance_transactions"
    )
    op.drop_index(
        "ix_balance_transactions_user_id", table_name="balance_transactions"
    )
    op.drop_table("balance_transactions")

    op.drop_index("ix_payments_meta_gin", table_name="payments")
    op.drop_index("ix_payments_created_at_desc", table_name="payments")
    op.drop_index("ix_payments_external_id", table_name="payments")
    op.drop_index("ix_payments_status", table_name="payments")
    op.drop_index("ix_payments_user_id", table_name="payments")
    op.drop_table("payments")

    op.drop_index("ix_subscriptions_user_free_trial", table_name="subscriptions")
    op.drop_index("ix_subscriptions_expires_at", table_name="subscriptions")
    op.drop_index("ix_subscriptions_status", table_name="subscriptions")
    op.drop_index("ix_subscriptions_user_id", table_name="subscriptions")
    op.drop_table("subscriptions")
