"""Outbox API endpoints used by the worker."""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy.exc import NoResultFound

from app.core.exceptions import NotFoundError
from app.deps import DBSession
from app.schemas.outbox import (
    OutboxAckResponse,
    OutboxFailedRequest,
    OutboxMessageResponse,
    OutboxPendingResponse,
    OutboxSentRequest,
)
from app.services import outbox_service

router = APIRouter()


@router.get("/outbox/pending", response_model=OutboxPendingResponse)
async def list_pending(
    session: DBSession,
    limit: int = Query(default=50, ge=1, le=200),
) -> OutboxPendingResponse:
    rows = await outbox_service.fetch_pending(session, limit=limit)
    await session.commit()
    return OutboxPendingResponse(
        items=[OutboxMessageResponse.model_validate(r) for r in rows]
    )


@router.post("/outbox/{message_id}/sent", response_model=OutboxAckResponse)
async def mark_sent(
    message_id: int,
    payload: OutboxSentRequest,
    session: DBSession,
) -> OutboxAckResponse:
    try:
        msg = await outbox_service.mark_sent(
            session,
            message_id=message_id,
            tg_message_id=payload.tg_message_id,
        )
    except NoResultFound as e:
        raise NotFoundError(
            f"Outbox message id={message_id} not found",
            error_code="outbox_not_found",
        ) from e
    await session.commit()
    return OutboxAckResponse(status=msg.status)


@router.post("/outbox/{message_id}/failed", response_model=OutboxAckResponse)
async def mark_failed(
    message_id: int,
    payload: OutboxFailedRequest,
    session: DBSession,
) -> OutboxAckResponse:
    try:
        msg = await outbox_service.mark_failed(
            session,
            message_id=message_id,
            error=payload.error,
        )
    except NoResultFound as e:
        raise NotFoundError(
            f"Outbox message id={message_id} not found",
            error_code="outbox_not_found",
        ) from e
    await session.commit()
    return OutboxAckResponse(status=msg.status)
