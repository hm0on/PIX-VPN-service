"""POST /api/bot/purchase/start — create a subscription payment + invoice."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.exceptions import NotFoundError
from app.deps import DBSession
from app.schemas.payment import PurchaseStartRequest, PurchaseStartResponse
from app.services.payment_service import PaymentService
from app.services.user_service import UserService

router = APIRouter()


@router.post("/purchase/start", response_model=PurchaseStartResponse)
async def purchase_start(
    payload: PurchaseStartRequest,
    session: DBSession,
) -> PurchaseStartResponse:
    user = await UserService(session).get_by_tg_id(payload.tg_id)
    if user is None:
        raise NotFoundError(
            f"User tg_id={payload.tg_id} not found", error_code="user_not_found"
        )

    service = PaymentService(session)
    result = await service.create_subscription_payment(
        user_id=user.id,
        tariff_id=payload.tariff_id,
        duration_id=payload.duration_id,
        provider=payload.provider,
        promo_id=payload.promo_id,
    )
    await session.commit()
    return PurchaseStartResponse(
        payment_id=result["payment_id"],
        subscription_id=result["subscription_id"],
        payment_url=result["payment_url"],
        expires_at=result["expires_at"],
        amount_kopecks=result["amount_kopecks"],
    )
