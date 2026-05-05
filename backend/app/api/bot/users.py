"""Bot user endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Response, status
from sqlalchemy import select

from app.core.exceptions import (
    AppError,
    NotFoundError,
)
from app.core.logging import LEVEL_INFO, business_log, get_logger
from app.db.models.user import User
from app.deps import DBSession
from app.schemas.ticket import BanRequest
from app.schemas.user import UserResponse, UserUpsertRequest, UserUpsertResponse
from app.services import referral_service
from app.services.user_service import UserService

logger = get_logger("users_api")

router = APIRouter()


def _parse_ref_payload(payload: str | None) -> int | None:
    """Parse `ref_<id>` payloads. Returns None on any malformed input."""
    if not payload:
        return None
    if not payload.startswith("ref_"):
        return None
    try:
        return int(payload[4:])
    except (TypeError, ValueError):
        return None


@router.post("/users", response_model=UserUpsertResponse)
async def upsert_user(payload: UserUpsertRequest, session: DBSession) -> UserUpsertResponse:
    service = UserService(session)
    user, created = await service.upsert_user(
        tg_id=payload.tg_id,
        username=payload.username,
        first_name=payload.first_name,
        last_name=payload.last_name,
        language_code=payload.language_code,
        ref_id=payload.ref_id,
    )

    # Best-effort referral registration: only for brand-new users with a
    # valid `ref_<id>` payload, and only if the referrer exists and is not
    # the same user.
    referrer_id = _parse_ref_payload(payload.start_payload)
    if created and referrer_id is not None and referrer_id != user.id:
        from sqlalchemy import select

        from app.db.models.user import User

        try:
            res = await session.execute(
                select(User).where(User.id == referrer_id)
            )
            referrer = res.scalar_one_or_none()
            if referrer is not None:
                try:
                    await referral_service.register_referral(
                        session,
                        referrer_user=referrer,
                        referee_user=user,
                        is_new=True,
                    )
                except AppError as e:
                    logger.info(
                        "referral_register_skipped",
                        error_code=e.error_code,
                        referrer_id=referrer_id,
                        referee_id=user.id,
                    )
        except Exception as e:  # noqa: BLE001 — never break upsert on bad payload
            logger.warning(
                "referral_register_failed",
                error=str(e),
                referrer_id=referrer_id,
                referee_id=user.id,
            )

    await session.commit()
    return UserUpsertResponse(
        user=UserResponse.model_validate(user),
        created=created,
    )


# NOTE: this route MUST be registered BEFORE ``/users/{tg_id}`` —
# otherwise FastAPI matches ``by-id`` as a literal ``tg_id`` value and
# trips int-coercion (422) instead of resolving here.
@router.get("/users/by-id/{user_id}", response_model=UserResponse)
async def get_user_by_id(user_id: int, session: DBSession) -> UserResponse:
    """Look up a user by primary-key id.

    Used by the bot's admin-side support flow: a ticket carries
    ``user_id`` (FK), and the bot needs the user's ``tg_id`` to deliver
    admin replies/notices into the user's DM.
    """
    service = UserService(session)
    user = await service.repo.get_by_id(user_id)
    if user is None:
        raise NotFoundError(
            f"User id={user_id} not found", error_code="user_not_found"
        )
    return UserResponse.model_validate(user)


@router.get("/users/{tg_id}", response_model=UserResponse)
async def get_user(tg_id: int, session: DBSession) -> UserResponse:
    service = UserService(session)
    user = await service.get_by_tg_id(tg_id)
    if user is None:
        raise NotFoundError(f"User tg_id={tg_id} not found", error_code="user_not_found")
    return UserResponse.model_validate(user)


async def _load_user_for_update(session, tg_id: int) -> User:  # noqa: ANN001
    """SELECT ... FOR UPDATE on a user by tg_id (no-op on SQLite)."""
    bind = session.get_bind()
    stmt = select(User).where(User.tg_id == tg_id)
    if bind is not None and bind.dialect.name != "sqlite":
        stmt = stmt.with_for_update()
    res = await session.execute(stmt)
    user = res.scalar_one_or_none()
    if user is None:
        raise NotFoundError(
            f"User tg_id={tg_id} not found", error_code="user_not_found"
        )
    return user


@router.post("/users/{tg_id}/ban", status_code=status.HTTP_204_NO_CONTENT)
async def ban_user(
    tg_id: int, payload: BanRequest, session: DBSession
) -> Response:
    user = await _load_user_for_update(session, tg_id)
    user.is_banned = True
    user.banned_reason = payload.reason
    await session.flush()

    await business_log(
        session,
        level=LEVEL_INFO,
        event="user_banned",
        user_id=user.id,
        message=f"User tg_id={tg_id} banned",
        context={"tg_id": tg_id, "reason": payload.reason},
    )

    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/users/{tg_id}/unban", status_code=status.HTTP_204_NO_CONTENT)
async def unban_user(tg_id: int, session: DBSession) -> Response:
    user = await _load_user_for_update(session, tg_id)
    user.is_banned = False
    user.banned_reason = None
    await session.flush()

    await business_log(
        session,
        level=LEVEL_INFO,
        event="user_unbanned",
        user_id=user.id,
        message=f"User tg_id={tg_id} unbanned",
        context={"tg_id": tg_id},
    )

    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
