"""Bot endpoints: profile / subscriptions / balance read paths."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, SubscriptionNotFoundError
from app.db.models.subscription import Subscription
from app.db.models.tariff import Tariff
from app.deps import DBSession
from app.schemas.balance import BalanceResponse
from app.schemas.subscription import SubscriptionResponse
from app.services.subscription_service import SubscriptionService
from app.services.user_service import UserService

router = APIRouter()


async def _tariff_name_map(
    session: AsyncSession, tariff_ids: list[int]
) -> dict[int, str]:
    """Bulk fetch ``{tariff_id: name}`` for the given ids.

    Used to denormalise the tariff label onto :class:`SubscriptionResponse`
    payloads without modelling a SQLAlchemy relationship on
    :class:`Subscription` (we want the API surface to stay lean and the join
    to remain explicit). Empty input returns an empty dict — no SQL emitted.
    """
    if not tariff_ids:
        return {}
    result = await session.execute(
        select(Tariff.id, Tariff.name).where(Tariff.id.in_(set(tariff_ids)))
    )
    return {tid: name for tid, name in result.all()}


def _serialise_subscription(
    sub: Subscription, *, tariff_name: str | None
) -> SubscriptionResponse:
    """Build a :class:`SubscriptionResponse` with ``tariff_name`` injected.

    ``model_validate`` already covers all ORM columns; we then overlay the
    joined ``tariff_name`` since it isn't a column on ``Subscription``.
    """
    payload = SubscriptionResponse.model_validate(sub)
    return payload.model_copy(update={"tariff_name": tariff_name})


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
    names = await _tariff_name_map(session, [s.tariff_id for s in subs])
    return [
        _serialise_subscription(s, tariff_name=names.get(s.tariff_id)) for s in subs
    ]


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
    names = await _tariff_name_map(session, [sub.tariff_id])
    return _serialise_subscription(sub, tariff_name=names.get(sub.tariff_id))
