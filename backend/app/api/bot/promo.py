"""Bot endpoint: validate & apply a promo code for a user."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.exceptions import NotFoundError
from app.deps import DBSession
from app.schemas.promo import PromoApplyRequest, PromoApplyResponse
from app.services.promo_service import PromoService
from app.services.user_service import UserService

router = APIRouter()


@router.post("/promo/apply", response_model=PromoApplyResponse)
async def apply_promo(
    payload: PromoApplyRequest,
    session: DBSession,
) -> PromoApplyResponse:
    user = await UserService(session).get_by_tg_id(payload.tg_id)
    if user is None:
        raise NotFoundError(
            f"User tg_id={payload.tg_id} not found",
            error_code="user_not_found",
        )

    service = PromoService(session)
    result = await service.validate_and_apply(code=payload.code, user=user)
    await session.commit()

    return PromoApplyResponse(
        type=result.type,
        amount_kopecks=result.amount_kopecks,
        percent=result.percent,
        promo_id=result.promo_id,
        message=result.message_text,
    )
