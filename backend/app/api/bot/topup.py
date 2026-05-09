"""POST /api/bot/topup/create — create a balance top-up payment."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.exceptions import NotFoundError
from app.deps import DBSession
from app.schemas.payment import TopupCreateRequest, TopupCreateResponse
from app.services.payment_service import PaymentService
from app.services.user_service import UserService

router = APIRouter()


@router.post("/topup/create", response_model=TopupCreateResponse)
async def topup_create(
    payload: TopupCreateRequest,
    session: DBSession,
) -> TopupCreateResponse:
    user = await UserService(session).get_by_tg_id(payload.tg_id)
    if user is None:
        raise NotFoundError(
            f"User tg_id={payload.tg_id} not found", error_code="user_not_found"
        )

    service = PaymentService(session)
    result = await service.create_topup_payment(
        user_id=user.id,
        amount_kopecks=payload.amount_kopecks,
        provider=payload.provider,
    )
    await session.commit()
    return TopupCreateResponse(
        payment_id=result["payment_id"],
        payment_url=result["payment_url"],
        expires_at=result["expires_at"],
        amount_kopecks=result["amount_kopecks"],
    )
