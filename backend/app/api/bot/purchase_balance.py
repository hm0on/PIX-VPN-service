"""Bot endpoint: purchase a subscription using the user's internal balance."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.exceptions import NotFoundError
from app.deps import DBSession, NorthLineClientDep
from app.schemas.balance import (
    PurchaseWithBalanceRequest,
    PurchaseWithBalanceResponse,
)
from app.schemas.subscription import SubscriptionResponse
from app.services.balance_service import BalanceService
from app.services.user_service import UserService

router = APIRouter()


@router.post("/purchase/balance", response_model=PurchaseWithBalanceResponse)
async def purchase_with_balance(
    payload: PurchaseWithBalanceRequest,
    session: DBSession,
    northline: NorthLineClientDep,
) -> PurchaseWithBalanceResponse:
    user = await UserService(session).get_by_tg_id(payload.tg_id)
    if user is None:
        raise NotFoundError(
            f"User tg_id={payload.tg_id} not found",
            error_code="user_not_found",
        )
    service = BalanceService(session, northline)
    sub, balance_after, payment_id = await service.purchase_with_balance(
        user=user,
        tariff_id=payload.tariff_id,
        duration_id=payload.duration_id,
        promo_id=payload.promo_id,
    )
    return PurchaseWithBalanceResponse(
        subscription=SubscriptionResponse.model_validate(sub),
        balance_after_kopecks=balance_after,
        payment_id=payment_id,
    )
