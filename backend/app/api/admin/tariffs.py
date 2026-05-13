"""Admin Tariffs router (Stage 5).

CRUD over Tariff + TariffDuration with audit log + Redis cache invalidation.
Soft-deletes only — hard delete is intentionally not supported because
historical payments may reference tariff/duration data via subscriptions.
"""

from __future__ import annotations

from fastapi import APIRouter, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.core.exceptions import (
    ConflictError,
    NotFoundError,
)
from app.db.models.tariff import Tariff, TariffDuration
from app.deps import AdminDep, DBSession, RedisDep
from app.schemas.admin_panel.tariff import (
    AdminTariff,
    AdminTariffCreate,
    AdminTariffDurationCreate,
    AdminTariffDurationPatch,
    AdminTariffPatch,
)
from app.schemas.common import OkResponse
from app.services.audit_service import record_admin_action
from app.services.tariff_service import TariffService

router = APIRouter()


# --------------------------------------------------------------------- #
# Tariff CRUD
# --------------------------------------------------------------------- #
@router.get("", response_model=list[AdminTariff])
async def list_tariffs(
    session: DBSession,
    _: AdminDep,
) -> list[AdminTariff]:
    result = await session.execute(
        select(Tariff)
        .options(selectinload(Tariff.durations))
        .order_by(Tariff.sort_order, Tariff.id)
    )
    rows = list(result.scalars().unique().all())
    return [AdminTariff.model_validate(r) for r in rows]


@router.post(
    "",
    response_model=AdminTariff,
    status_code=status.HTTP_201_CREATED,
)
async def create_tariff(
    payload: AdminTariffCreate,
    session: DBSession,
    redis: RedisDep,
    admin: AdminDep,
) -> AdminTariff:
    tariff_kwargs: dict[str, object] = dict(
        code=payload.code,
        name=payload.name,
        description_html=payload.description_html,
        devices=payload.devices,
        sort_order=payload.sort_order,
        is_active=payload.is_active,
        is_free_trial=payload.is_free_trial,
        free_trial_days=payload.free_trial_days,
    )
    # Conversion-pack 2026-05-13: traffic_gb_per_month + lte_gb_per_month
    # передаются только если админ их указал — иначе остаются дефолты
    # модели (NULL и 35 GB соответственно).
    if payload.traffic_gb_per_month is not None:
        tariff_kwargs["traffic_gb_per_month"] = payload.traffic_gb_per_month
    if payload.lte_gb_per_month is not None:
        tariff_kwargs["lte_gb_per_month"] = payload.lte_gb_per_month
    tariff = Tariff(**tariff_kwargs)
    session.add(tariff)
    try:
        await session.flush()
    except IntegrityError as e:
        await session.rollback()
        raise ConflictError(
            f"Tariff with code '{payload.code}' already exists",
            error_code="tariff_code_conflict",
        ) from e

    await record_admin_action(
        session,
        admin,
        "tariff.create",
        extra={"tariff_id": tariff.id, "code": tariff.code},
    )
    await session.commit()
    await TariffService.invalidate_cache(redis)

    # Reload with durations (empty)
    await session.refresh(tariff, attribute_names=["durations"])
    return AdminTariff.model_validate(tariff)


@router.patch("/{tariff_id}", response_model=AdminTariff)
async def patch_tariff(
    tariff_id: int,
    payload: AdminTariffPatch,
    session: DBSession,
    redis: RedisDep,
    admin: AdminDep,
) -> AdminTariff:
    tariff = await session.get(Tariff, tariff_id)
    if tariff is None:
        raise NotFoundError("Tariff not found", error_code="tariff_not_found")

    changes: dict[str, object] = {}
    for field in (
        "name",
        "description_html",
        "devices",
        "sort_order",
        "is_active",
        "is_free_trial",
        "free_trial_days",
        "traffic_gb_per_month",
        "lte_gb_per_month",
    ):
        new_val = getattr(payload, field)
        if new_val is not None:
            setattr(tariff, field, new_val)
            changes[field] = new_val

    if changes:
        await session.flush()
        await record_admin_action(
            session,
            admin,
            "tariff.update",
            extra={"tariff_id": tariff.id, "changes": changes},
        )

    await session.commit()
    await TariffService.invalidate_cache(redis)

    await session.refresh(tariff, attribute_names=["durations"])
    return AdminTariff.model_validate(tariff)


@router.delete("/{tariff_id}", response_model=OkResponse)
async def delete_tariff(
    tariff_id: int,
    session: DBSession,
    redis: RedisDep,
    admin: AdminDep,
) -> OkResponse:
    tariff = await session.get(Tariff, tariff_id)
    if tariff is None:
        raise NotFoundError("Tariff not found", error_code="tariff_not_found")

    if tariff.is_active:
        tariff.is_active = False
        await session.flush()
        await record_admin_action(
            session,
            admin,
            "tariff.soft_delete",
            extra={"tariff_id": tariff.id, "code": tariff.code},
        )
    await session.commit()
    await TariffService.invalidate_cache(redis)
    return OkResponse(ok=True)


# --------------------------------------------------------------------- #
# Tariff Duration CRUD
# --------------------------------------------------------------------- #
@router.post(
    "/{tariff_id}/durations",
    response_model=AdminTariff,
    status_code=status.HTTP_201_CREATED,
)
async def create_duration(
    tariff_id: int,
    payload: AdminTariffDurationCreate,
    session: DBSession,
    redis: RedisDep,
    admin: AdminDep,
) -> AdminTariff:
    tariff = await session.get(Tariff, tariff_id)
    if tariff is None:
        raise NotFoundError("Tariff not found", error_code="tariff_not_found")

    duration = TariffDuration(
        tariff_id=tariff_id,
        days=payload.days,
        price_kopecks=payload.price_kopecks,
        is_hot=payload.is_hot,
        is_active=payload.is_active,
    )
    session.add(duration)
    try:
        await session.flush()
    except IntegrityError as e:
        await session.rollback()
        raise ConflictError(
            f"Duration days={payload.days} already exists for this tariff",
            error_code="tariff_duration_conflict",
        ) from e

    await record_admin_action(
        session,
        admin,
        "tariff.duration.create",
        extra={
            "tariff_id": tariff_id,
            "duration_id": duration.id,
            "days": duration.days,
            "price_kopecks": duration.price_kopecks,
        },
    )
    await session.commit()
    await TariffService.invalidate_cache(redis)

    await session.refresh(tariff, attribute_names=["durations"])
    return AdminTariff.model_validate(tariff)


@router.patch(
    "/{tariff_id}/durations/{duration_id}",
    response_model=AdminTariff,
)
async def patch_duration(
    tariff_id: int,
    duration_id: int,
    payload: AdminTariffDurationPatch,
    session: DBSession,
    redis: RedisDep,
    admin: AdminDep,
) -> AdminTariff:
    duration = await session.get(TariffDuration, duration_id)
    if duration is None or duration.tariff_id != tariff_id:
        raise NotFoundError(
            "Tariff duration not found",
            error_code="tariff_duration_not_found",
        )

    changes: dict[str, object] = {}
    for field in ("price_kopecks", "is_hot", "is_active"):
        new_val = getattr(payload, field)
        if new_val is not None:
            setattr(duration, field, new_val)
            changes[field] = new_val

    if changes:
        await session.flush()
        await record_admin_action(
            session,
            admin,
            "tariff.duration.update",
            extra={
                "tariff_id": tariff_id,
                "duration_id": duration_id,
                "changes": changes,
            },
        )
    await session.commit()
    await TariffService.invalidate_cache(redis)

    tariff = await session.get(Tariff, tariff_id)
    assert tariff is not None
    await session.refresh(tariff, attribute_names=["durations"])
    return AdminTariff.model_validate(tariff)


@router.delete(
    "/{tariff_id}/durations/{duration_id}",
    response_model=OkResponse,
)
async def delete_duration(
    tariff_id: int,
    duration_id: int,
    session: DBSession,
    redis: RedisDep,
    admin: AdminDep,
) -> OkResponse:
    duration = await session.get(TariffDuration, duration_id)
    if duration is None or duration.tariff_id != tariff_id:
        raise NotFoundError(
            "Tariff duration not found",
            error_code="tariff_duration_not_found",
        )

    if duration.is_active:
        duration.is_active = False
        await session.flush()
        await record_admin_action(
            session,
            admin,
            "tariff.duration.soft_delete",
            extra={
                "tariff_id": tariff_id,
                "duration_id": duration_id,
            },
        )
    await session.commit()
    await TariffService.invalidate_cache(redis)
    return OkResponse(ok=True)
