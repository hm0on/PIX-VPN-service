"""Bot endpoint: activate the FREE-trial subscription."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.exceptions import NotFoundError
from app.deps import DBSession, NorthLineClientDep
from app.schemas.subscription import (
    FreeTrialRequest,
    FreeTrialResponse,
    SubscriptionResponse,
)
from app.services.free_trial_service import FreeTrialService
from app.services.user_service import UserService

router = APIRouter()


@router.post("/free-trial", response_model=FreeTrialResponse)
async def activate_free_trial(
    payload: FreeTrialRequest,
    session: DBSession,
    northline: NorthLineClientDep,
) -> FreeTrialResponse:
    user = await UserService(session).get_by_tg_id(payload.tg_id)
    if user is None:
        raise NotFoundError(
            f"User tg_id={payload.tg_id} not found",
            error_code="user_not_found",
        )
    service = FreeTrialService(session, northline)
    sub = await service.activate_free_trial(user=user)
    return FreeTrialResponse(subscription=SubscriptionResponse.model_validate(sub))
