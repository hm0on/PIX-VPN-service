"""Bot endpoint: referral stats screen."""

from __future__ import annotations

from fastapi import APIRouter

from app.config import get_settings
from app.core.exceptions import NotFoundError
from app.deps import DBSession
from app.schemas.referral import ReferralStatsResponse
from app.services import referral_service
from app.services.user_service import UserService

router = APIRouter()


def _build_ref_link(user_id: int) -> str:
    settings = get_settings()
    bot_username = (settings.public_bot_username or "your_bot").lstrip("@")
    return f"https://t.me/{bot_username}?start=ref_{user_id}"


@router.get(
    "/users/{tg_id}/referral-stats",
    response_model=ReferralStatsResponse,
)
async def get_referral_stats(
    tg_id: int, session: DBSession
) -> ReferralStatsResponse:
    user = await UserService(session).get_by_tg_id(tg_id)
    if user is None:
        raise NotFoundError(
            f"User tg_id={tg_id} not found", error_code="user_not_found"
        )
    stats = await referral_service.get_stats(session, user.id)
    return ReferralStatsResponse(
        invited=stats.invited,
        earned_kopecks=stats.earned_kopecks,
        ref_link=_build_ref_link(user.id),
    )
