"""Bot support-topic cache endpoints (Stage 4)."""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.deps import DBSession
from app.schemas.ticket import (
    SupportTopicResponse,
    SupportTopicSaveRequest,
)
from app.services import ticket_service

router = APIRouter()


@router.get("/support-topic/{user_id}", response_model=SupportTopicResponse)
async def get_support_topic(
    user_id: int, session: DBSession
) -> SupportTopicResponse:
    topic = await ticket_service.get_support_topic(session, user_id)
    if topic is None:
        return SupportTopicResponse(topic_thread_id=None, topic_name=None)
    return SupportTopicResponse(
        topic_thread_id=topic.topic_thread_id,
        topic_name=topic.topic_name,
    )


@router.post("/support-topic", status_code=status.HTTP_204_NO_CONTENT)
async def save_support_topic(
    payload: SupportTopicSaveRequest, session: DBSession
) -> Response:
    await ticket_service.save_support_topic(
        session,
        user_id=payload.user_id,
        topic_thread_id=payload.topic_thread_id,
        topic_name=payload.topic_name,
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
