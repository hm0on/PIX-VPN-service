"""Ticket service (Stage 4)."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    TicketAlreadyClosedError,
    TicketAlreadyOpenError,
    TicketNotFoundError,
)
from app.core.logging import LEVEL_INFO, business_log, get_logger, tech_log
from app.db.models.support_topic import SupportTopic
from app.db.models.ticket import (
    TICKET_STATUS_CLOSED,
    TICKET_STATUS_OPEN,
    Ticket,
)
from app.db.models.ticket_message import TicketMessage
from app.repositories.support_topic_repo import SupportTopicRepository
from app.repositories.ticket_message_repo import TicketMessageRepository
from app.repositories.ticket_repo import TicketRepository
from app.repositories.user_repo import UserRepository

logger = get_logger("ticket_service")

# 6-character base36 — 36**6 == 2_176_782_336 distinct codes.
_CODE_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_CODE_LENGTH = 6
_CODE_RETRY_LIMIT = 5


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _generate_code() -> str:
    """Generate a TCK-XXXXXX code with 6 base36 characters from CSPRNG."""
    rand_bytes = secrets.token_bytes(_CODE_LENGTH)
    chars = "".join(_CODE_ALPHABET[b % 36] for b in rand_bytes)
    return f"TCK-{chars}"


# ---------------------------------------------------------------------------
# Ticket lifecycle
# ---------------------------------------------------------------------------


async def open_ticket(
    session: AsyncSession,
    *,
    user_id: int,
    kind: str,
) -> Ticket:
    """Open a fresh ticket for a user, generating a unique code.

    Raises:
        TicketAlreadyOpenError: user already has an open ticket
            (caught via the partial UNIQUE index `(user_id) WHERE status='open'`).
    """
    # Pre-check (best-effort) to surface a friendly error before relying on
    # the unique index trip.
    repo = TicketRepository(session)
    existing = await repo.get_active_for_user(user_id)
    if existing is not None:
        raise TicketAlreadyOpenError(
            "User already has an open ticket",
            details={"ticket_id": existing.id, "code": existing.code},
        )

    last_error: Exception | None = None
    ticket: Ticket | None = None
    for _attempt in range(_CODE_RETRY_LIMIT):
        code = _generate_code()
        savepoint = await session.begin_nested()
        try:
            ticket = Ticket(
                code=code,
                user_id=user_id,
                kind=kind,
                status=TICKET_STATUS_OPEN,
            )
            session.add(ticket)
            await session.flush()
        except IntegrityError as e:
            await savepoint.rollback()
            last_error = e
            ticket = None
            # Could be a code collision OR the partial-unique violation.
            # Re-check the open-ticket invariant: if hit, raise AlreadyOpen.
            existing = await repo.get_active_for_user(user_id)
            if existing is not None:
                raise TicketAlreadyOpenError(
                    "User already has an open ticket",
                    details={"ticket_id": existing.id, "code": existing.code},
                ) from e
            continue
        else:
            await savepoint.commit()
            await session.refresh(ticket)
            break

    if ticket is None:
        logger.error(
            "ticket_code_generation_exhausted",
            user_id=user_id,
            attempts=_CODE_RETRY_LIMIT,
        )
        raise RuntimeError(
            "Failed to generate a unique ticket code after retries"
        ) from last_error

    await business_log(
        session,
        level=LEVEL_INFO,
        event="ticket_opened",
        user_id=user_id,
        message=f"Opened ticket {ticket.code} (kind={kind})",
        context={
            "ticket_id": ticket.id,
            "code": ticket.code,
            "kind": kind,
        },
    )
    return ticket


async def close_ticket(
    session: AsyncSession,
    *,
    ticket_id: int,
    by: str,
    user_tg_id: int | None = None,
) -> Ticket:
    """Close a ticket. If user_tg_id is given, also verify ownership.

    Raises:
        TicketNotFoundError: no such ticket (or not owned by the user).
        TicketAlreadyClosedError: ticket is already closed.
    """
    repo = TicketRepository(session)
    ticket = await repo.get_by_id(ticket_id)
    if ticket is None:
        raise TicketNotFoundError(
            "Ticket not found", details={"ticket_id": ticket_id}
        )

    if user_tg_id is not None:
        user = await UserRepository(session).get_by_tg_id(user_tg_id)
        if user is None or ticket.user_id != user.id:
            # Treat ownership mismatch as 404 to avoid leaking ticket existence.
            raise TicketNotFoundError(
                "Ticket not found",
                details={"ticket_id": ticket_id, "tg_user_id": user_tg_id},
            )

    if ticket.status == TICKET_STATUS_CLOSED:
        raise TicketAlreadyClosedError(
            "Ticket is already closed",
            details={"ticket_id": ticket_id, "code": ticket.code},
        )

    when = _now()
    updated = await repo.mark_closed(ticket_id, by=by, when=when)
    assert updated is not None  # mark_closed reads after write

    await business_log(
        session,
        level=LEVEL_INFO,
        event="ticket_closed",
        user_id=updated.user_id,
        message=f"Closed ticket {updated.code} (by={by})",
        context={
            "ticket_id": updated.id,
            "code": updated.code,
            "closed_by": by,
        },
    )
    return updated


async def record_message(
    session: AsyncSession,
    *,
    ticket_id: int,
    direction: str,
    message_type: str,
    text: str | None = None,
    photo_file_id: str | None = None,
    sticker_file_id: str | None = None,
    tg_message_id: int | None = None,
) -> TicketMessage:
    """Persist a TicketMessage and bump the parent ticket's updated_at.

    Raises TicketNotFoundError if the ticket doesn't exist.
    """
    repo = TicketRepository(session)
    ticket = await repo.get_by_id(ticket_id)
    if ticket is None:
        raise TicketNotFoundError(
            "Ticket not found", details={"ticket_id": ticket_id}
        )

    msg_repo = TicketMessageRepository(session)
    row = await msg_repo.create(
        ticket_id=ticket_id,
        direction=direction,
        message_type=message_type,
        text=text,
        photo_file_id=photo_file_id,
        sticker_file_id=sticker_file_id,
        tg_message_id=tg_message_id,
    )

    # Bump the parent ticket's updated_at so the topic stays "fresh".
    await repo.touch(ticket_id, when=_now())

    await tech_log(
        session,
        action="ticket_message_recorded",
        user_id=ticket.user_id,
        payload={
            "ticket_id": ticket_id,
            "ticket_code": ticket.code,
            "direction": direction,
            "message_type": message_type,
            "tg_message_id": tg_message_id,
        },
    )
    return row


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------


async def get_active_ticket_for_user(
    session: AsyncSession, tg_user_id: int
) -> Ticket | None:
    """Resolve tg_id → user_id, then return their active ticket (or None)."""
    user = await UserRepository(session).get_by_tg_id(tg_user_id)
    if user is None:
        return None
    return await TicketRepository(session).get_active_for_user(user.id)


async def get_ticket_by_thread(
    session: AsyncSession, thread_id: int
) -> Ticket | None:
    return await TicketRepository(session).get_by_thread(thread_id)


async def set_ticket_topic_thread_id(
    session: AsyncSession, *, ticket_id: int, thread_id: int
) -> Ticket:
    repo = TicketRepository(session)
    ticket = await repo.get_by_id(ticket_id)
    if ticket is None:
        raise TicketNotFoundError(
            "Ticket not found", details={"ticket_id": ticket_id}
        )
    updated = await repo.set_topic_thread_id(ticket_id, thread_id)
    assert updated is not None
    return updated


# ---------------------------------------------------------------------------
# Support topics (per-user forum thread cache)
# ---------------------------------------------------------------------------


async def save_support_topic(
    session: AsyncSession,
    *,
    user_id: int,
    topic_thread_id: int,
    topic_name: str,
) -> SupportTopic:
    return await SupportTopicRepository(session).upsert(
        user_id=user_id,
        topic_thread_id=topic_thread_id,
        topic_name=topic_name,
    )


async def get_support_topic(
    session: AsyncSession, user_id: int
) -> SupportTopic | None:
    return await SupportTopicRepository(session).get_by_user_id(user_id)
