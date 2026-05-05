"""Bot endpoint: subscription extension."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.exceptions import NotFoundError
from app.deps import DBSession, NorthLineClientDep
from app.schemas.extension import ExtensionStartRequest, ExtensionStartResponse
from app.services.extension_service import create_extension_payment
from app.services.user_service import UserService

router = APIRouter()


@router.post(
    "/subscriptions/{subscription_id}/extend",
    response_model=ExtensionStartResponse,
)
async def extend_subscription(
    subscription_id: int,
    payload: ExtensionStartRequest,
    session: DBSession,
    northline: NorthLineClientDep,
) -> ExtensionStartResponse:
    user = await UserService(session).get_by_tg_id(payload.tg_id)
    if user is None:
        raise NotFoundError(
            f"User tg_id={payload.tg_id} not found",
            error_code="user_not_found",
        )

    result = await create_extension_payment(
        session,
        subscription_id=subscription_id,
        duration_id=payload.duration_id,
        user=user,
        payment_provider=payload.payment_provider,
        promo_code=payload.promo_code,
        northline_client=northline,
    )
    await session.commit()
    return ExtensionStartResponse(
        payment_id=result.payment_id,
        amount_kopecks=result.amount_kopecks,
        payment_url=result.payment_url,
        key_url=result.key_url,
    )
