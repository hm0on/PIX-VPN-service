"""Initial Stage 1 schema

Revision ID: 0001_initial_stage1
Revises:
Create Date: 2026-05-04 00:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_stage1"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # users
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tg_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column("first_name", sa.String(length=128), nullable=True),
        sa.Column("last_name", sa.String(length=128), nullable=True),
        sa.Column("language_code", sa.String(length=8), nullable=True),
        sa.Column("balance_kopecks", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("is_banned", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("banned_reason", sa.Text(), nullable=True),
        sa.Column("ref_id", sa.BigInteger(), nullable=True),
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
        sa.UniqueConstraint("tg_id", name="uq_users_tg_id"),
        sa.ForeignKeyConstraint(["ref_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_users_tg_id", "users", ["tg_id"])
    op.create_index("ix_users_ref_id", "users", ["ref_id"])
    op.create_index("ix_users_created_at", "users", ["created_at"])

    # tariffs
    op.create_table(
        "tariffs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description_html", sa.Text(), nullable=True),
        sa.Column("devices", sa.Integer(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("is_free_trial", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("free_trial_days", sa.Integer(), nullable=True),
        sa.UniqueConstraint("code", name="uq_tariffs_code"),
    )

    # tariff_durations
    op.create_table(
        "tariff_durations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tariff_id", sa.Integer(), nullable=False),
        sa.Column("days", sa.Integer(), nullable=False),
        sa.Column("price_kopecks", sa.BigInteger(), nullable=False),
        sa.Column("is_hot", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.ForeignKeyConstraint(["tariff_id"], ["tariffs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("tariff_id", "days", name="uq_tariff_durations_tariff_days"),
    )

    # texts
    op.create_table(
        "texts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("value_html", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_by", sa.String(length=128), nullable=True),
        sa.UniqueConstraint("key", name="uq_texts_key"),
    )

    # logs
    op.create_table(
        "logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("level", sa.SmallInteger(), nullable=False),
        sa.Column("event", sa.String(length=128), nullable=False),
        sa.Column("module", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("context", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_logs_level", "logs", ["level"])
    op.create_index("ix_logs_module", "logs", ["module"])
    op.create_index("ix_logs_user_id", "logs", ["user_id"])
    op.create_index("ix_logs_created_at_desc", "logs", ["created_at"])
    op.create_index(
        "ix_logs_context_gin", "logs", ["context"], postgresql_using="gin"
    )

    # tech_logs
    op.create_table(
        "tech_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("trace_id", sa.String(length=36), nullable=False),
        sa.Column("service", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_tech_logs_trace_id", "tech_logs", ["trace_id"])
    op.create_index("ix_tech_logs_created_at_desc", "tech_logs", ["created_at"])
    op.create_index("ix_tech_logs_service", "tech_logs", ["service"])
    op.create_index("ix_tech_logs_action", "tech_logs", ["action"])

    # admin_keys
    op.create_table(
        "admin_keys",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("key_hash", sa.String(length=255), nullable=False),
        sa.Column("label", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("key_hash", name="uq_admin_keys_key_hash"),
    )


def downgrade() -> None:
    op.drop_table("admin_keys")
    op.drop_index("ix_tech_logs_action", table_name="tech_logs")
    op.drop_index("ix_tech_logs_service", table_name="tech_logs")
    op.drop_index("ix_tech_logs_created_at_desc", table_name="tech_logs")
    op.drop_index("ix_tech_logs_trace_id", table_name="tech_logs")
    op.drop_table("tech_logs")
    op.drop_index("ix_logs_context_gin", table_name="logs")
    op.drop_index("ix_logs_created_at_desc", table_name="logs")
    op.drop_index("ix_logs_user_id", table_name="logs")
    op.drop_index("ix_logs_module", table_name="logs")
    op.drop_index("ix_logs_level", table_name="logs")
    op.drop_table("logs")
    op.drop_table("texts")
    op.drop_table("tariff_durations")
    op.drop_table("tariffs")
    op.drop_index("ix_users_created_at", table_name="users")
    op.drop_index("ix_users_ref_id", table_name="users")
    op.drop_index("ix_users_tg_id", table_name="users")
    op.drop_table("users")
