"""Bot ticket endpoints (Stage 4)."""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.core.exceptions import NotFoundError
from app.deps import DBSession
from app.schemas.ticket import (
    TicketActiveResponse,
    TicketByThreadResponse,
    TicketCloseRequest,
    TicketMessageCreateRequest,
    TicketOpenRequest,
    TicketResponse,
    TopicAttachRequest,
)
from app.services import ticket_service
from app.services.user_service import UserService

router = APIRouter()


@router.post("/tickets/open", response_model=TicketResponse)
async def open_ticket(
    payload: TicketOpenRequest, session: DBSession
) -> TicketResponse:
    user = await UserService(session).get_by_tg_id(payload.tg_user_id)
    if user is None:
        raise NotFoundError(
            f"User tg_id={payload.tg_user_id} not found",
            error_code="user_not_found",
        )

    ticket = await ticket_service.open_ticket(
        session, user_id=user.id, kind=payload.kind
    )
    await session.commit()
    return TicketResponse.model_validate(ticket)


@router.post("/tickets/{ticket_id}/close", response_model=TicketResponse)
async def close_ticket(
    ticket_id: int, payload: TicketCloseRequest, session: DBSession
) -> TicketResponse:
    ticket = await ticket_service.close_ticket(
        session,
        ticket_id=ticket_id,
        by=payload.by,
        user_tg_id=payload.tg_user_id,
    )
    await session.commit()
    return TicketResponse.model_validate(ticket)


@router.post(
    "/tickets/{ticket_id}/messages",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def post_ticket_message(
    ticket_id: int,
    payload: TicketMessageCreateRequest,
    session: DBSession,
) -> Response:
    await ticket_service.record_message(
        session,
        ticket_id=ticket_id,
        direction=payload.direction,
        message_type=payload.message_type,
        text=payload.text,
        photo_file_id=payload.photo_file_id,
        sticker_file_id=payload.sticker_file_id,
        tg_message_id=payload.tg_message_id,
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/users/{tg_id}/active-ticket", response_model=TicketActiveResponse
)
async def get_active_ticket(
    tg_id: int, session: DBSession
) -> TicketActiveResponse:
    ticket = await ticket_service.get_active_ticket_for_user(session, tg_id)
    if ticket is None:
        return TicketActiveResponse(ticket=None)
    return TicketActiveResponse(ticket=TicketResponse.model_validate(ticket))


@router.get(
    "/tickets/by-thread/{thread_id}", response_model=TicketByThreadResponse
)
async def get_ticket_by_thread(
    thread_id: int, session: DBSession
) -> TicketByThreadResponse:
    ticket = await ticket_service.get_ticket_by_thread(session, thread_id)
    if ticket is None:
        return TicketByThreadResponse(ticket=None)
    return TicketByThreadResponse(
        ticket=TicketResponse.model_validate(ticket)
    )


@router.post(
    "/tickets/{ticket_id}/topic",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def attach_ticket_topic(
    ticket_id: int,
    payload: TopicAttachRequest,
    session: DBSession,
) -> Response:
    await ticket_service.set_ticket_topic_thread_id(
        session, ticket_id=ticket_id, thread_id=payload.topic_thread_id
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
