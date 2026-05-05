"""Stage 4 schema: tickets, ticket_messages, support_topics

Revision ID: 0004_stage4
Revises: 0003_stage3
Create Date: 2026-05-05 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_stage4"
down_revision: str | None = "0003_stage3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # tickets
    op.create_table(
        "tickets",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="open",
            nullable=False,
        ),
        sa.Column("closed_by", sa.String(length=16), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("topic_thread_id", sa.BigInteger(), nullable=True),
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
        sa.UniqueConstraint("code", name="uq_tickets_code"),
    )
    op.create_index("ix_tickets_code", "tickets", ["code"], unique=True)
    op.create_index(
        "ix_tickets_topic_thread_id", "tickets", ["topic_thread_id"]
    )
    op.create_index("ix_tickets_user_id", "tickets", ["user_id"])

    # Partial UNIQUE index — guarantees "1 open ticket per user".
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.create_index(
            "uq_tickets_user_open",
            "tickets",
            ["user_id"],
            unique=True,
            postgresql_where=sa.text("status = 'open'"),
        )
    else:
        # SQLite supports partial indexes via CREATE INDEX ... WHERE
        op.create_index(
            "uq_tickets_user_open",
            "tickets",
            ["user_id"],
            unique=True,
            sqlite_where=sa.text("status = 'open'"),
        )

    # ticket_messages
    op.create_table(
        "ticket_messages",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("ticket_id", sa.BigInteger(), nullable=False),
        sa.Column("direction", sa.String(length=8), nullable=False),
        sa.Column("message_type", sa.String(length=16), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("photo_file_id", sa.String(length=255), nullable=True),
        sa.Column("sticker_file_id", sa.String(length=255), nullable=True),
        sa.Column("tg_message_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id"], ["tickets.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_ticket_messages_ticket_id", "ticket_messages", ["ticket_id"]
    )
    op.create_index(
        "ix_ticket_messages_created_at", "ticket_messages", ["created_at"]
    )

    # support_topics
    op.create_table(
        "support_topics",
        sa.Column(
            "user_id",
            sa.BigInteger(),
            primary_key=True,
            autoincrement=False,
            nullable=False,
        ),
        sa.Column("topic_thread_id", sa.BigInteger(), nullable=False),
        sa.Column("topic_name", sa.String(length=255), nullable=True),
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
        sa.UniqueConstraint(
            "topic_thread_id", name="uq_support_topics_topic_thread_id"
        ),
    )


def downgrade() -> None:
    op.drop_table("support_topics")

    op.drop_index(
        "ix_ticket_messages_created_at", table_name="ticket_messages"
    )
    op.drop_index(
        "ix_ticket_messages_ticket_id", table_name="ticket_messages"
    )
    op.drop_table("ticket_messages")

    op.drop_index("uq_tickets_user_open", table_name="tickets")
    op.drop_index("ix_tickets_user_id", table_name="tickets")
    op.drop_index("ix_tickets_topic_thread_id", table_name="tickets")
    op.drop_index("ix_tickets_code", table_name="tickets")
    op.drop_table("tickets")
