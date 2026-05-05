"""Bot endpoints: profile / subscriptions / balance read paths."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.core.exceptions import NotFoundError, SubscriptionNotFoundError
from app.deps import DBSession
from app.schemas.balance import BalanceResponse
from app.schemas.subscription import SubscriptionResponse
from app.services.subscription_service import SubscriptionService
from app.services.user_service import UserService

router = APIRouter()


@router.get(
    "/users/{tg_id}/subscriptions",
    response_model=list[SubscriptionResponse],
)
async def list_user_subscriptions(
    tg_id: int, session: DBSession
) -> list[SubscriptionResponse]:
    user = await UserService(session).get_by_tg_id(tg_id)
    if user is None:
        raise NotFoundError(
            f"User tg_id={tg_id} not found", error_code="user_not_found"
        )
    service = SubscriptionService(session)
    subs = await service.get_user_subscriptions(user_id=user.id)
    return [SubscriptionResponse.model_validate(s) for s in subs]


@router.get("/users/{tg_id}/balance", response_model=BalanceResponse)
async def get_user_balance(tg_id: int, session: DBSession) -> BalanceResponse:
    user = await UserService(session).get_by_tg_id(tg_id)
    if user is None:
        raise NotFoundError(
            f"User tg_id={tg_id} not found", error_code="user_not_found"
        )
    return BalanceResponse(balance_kopecks=int(user.balance_kopecks))


@router.get(
    "/subscriptions/{subscription_id}",
    response_model=SubscriptionResponse,
)
async def get_subscription_detail(
    subscription_id: int,
    tg_id: Annotated[int, Query(..., description="Owner tg_id (ownership check)")],
    session: DBSession,
) -> SubscriptionResponse:
    user = await UserService(session).get_by_tg_id(tg_id)
    if user is None:
        raise NotFoundError(
            f"User tg_id={tg_id} not found", error_code="user_not_found"
        )
    service = SubscriptionService(session)
    sub = await service.get_subscription_detail(
        subscription_id=subscription_id, user_id=user.id
    )
    if sub is None:
        raise SubscriptionNotFoundError(
            f"Subscription id={subscription_id} not found"
        )
    return SubscriptionResponse.model_validate(sub)
