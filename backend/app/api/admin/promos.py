"""Admin Promo Codes router (Stage 5)."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import (
    ConflictError,
    NotFoundError,
    ValidationError,
)
from app.db.models.promo_activation import PromoActivation
from app.db.models.promo_code import PROMO_TYPES, PromoCode
from app.deps import AdminDep, DBSession
from app.schemas.admin_panel.promo import (
    AdminPromo,
    AdminPromoActivation,
    AdminPromoCreate,
    AdminPromoPatch,
    AdminPromosPage,
)
from app.services.audit_service import record_admin_action

router = APIRouter()


# ASCII alphabet excluding ambiguous chars (0/O, 1/I/l).
_PROMO_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_PROMO_LEN = 8


def _generate_promo_code() -> str:
    return "".join(secrets.choice(_PROMO_ALPHABET) for _ in range(_PROMO_LEN))


# --------------------------------------------------------------------- #
@router.get("", response_model=AdminPromosPage)
async def list_promos(
    session: DBSession,
    _: AdminDep,
    is_active: bool | None = None,
    code: str | None = Query(default=None, max_length=64),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> AdminPromosPage:
    stmt = select(PromoCode)
    if is_active is not None:
        stmt = stmt.where(PromoCode.is_active.is_(is_active))
    if code:
        stmt = stmt.where(PromoCode.code.ilike(f"%{code}%"))

    total_q = select(func.count()).select_from(stmt.subquery())
    total_res = await session.execute(total_q)
    total = int(total_res.scalar() or 0)

    rows_res = await session.execute(
        stmt.order_by(PromoCode.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = rows_res.scalars().all()
    items = [AdminPromo.model_validate(r) for r in rows]
    return AdminPromosPage(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "",
    response_model=AdminPromo,
    status_code=status.HTTP_201_CREATED,
)
async def create_promo(
    payload: AdminPromoCreate,
    session: DBSession,
    admin: AdminDep,
) -> AdminPromo:
    if payload.type not in PROMO_TYPES:
        raise ValidationError(
            f"Invalid promo type: {payload.type}",
            error_code="invalid_promo_type",
        )
    if (
        payload.valid_from is not None
        and payload.valid_until is not None
        and payload.valid_from >= payload.valid_until
    ):
        raise ValidationError(
            "valid_from must be earlier than valid_until",
            error_code="invalid_promo_window",
        )

    code = (payload.code or _generate_promo_code()).upper()

    promo = PromoCode(
        code=code,
        type=payload.type,
        value=payload.value,
        max_total_activations=payload.max_total_activations,
        max_per_user=payload.max_per_user,
        valid_from=payload.valid_from,
        valid_until=payload.valid_until,
        is_active=payload.is_active,
        description=payload.description,
        created_by_admin_key_label=admin.label,
    )
    session.add(promo)
    try:
        await session.flush()
    except IntegrityError as e:
        await session.rollback()
        raise ConflictError(
            f"Promo code '{code}' already exists",
            error_code="promo_code_conflict",
        ) from e

    await record_admin_action(
        session,
        admin,
        "promo.create",
        extra={"promo_id": promo.id, "code": promo.code, "type": promo.type},
    )
    await session.commit()
    await session.refresh(promo)
    return AdminPromo.model_validate(promo)


@router.patch("/{promo_id}", response_model=AdminPromo)
async def patch_promo(
    promo_id: int,
    payload: AdminPromoPatch,
    session: DBSession,
    admin: AdminDep,
) -> AdminPromo:
    promo = await session.get(PromoCode, promo_id)
    if promo is None:
        raise NotFoundError("Promo not found", error_code="promo_not_found")

    changes: dict[str, object] = {}
    if payload.is_active is not None:
        promo.is_active = payload.is_active
        changes["is_active"] = payload.is_active
    if payload.max_total_activations is not None:
        # 0 → reset to NULL ("unlimited") for convenience
        promo.max_total_activations = (
            payload.max_total_activations or None
        )
        changes["max_total_activations"] = promo.max_total_activations
    if payload.max_per_user is not None:
        promo.max_per_user = payload.max_per_user
        changes["max_per_user"] = payload.max_per_user
    if payload.valid_until is not None:
        promo.valid_until = payload.valid_until
        changes["valid_until"] = payload.valid_until.isoformat()

    if changes:
        await session.flush()
        await record_admin_action(
            session,
            admin,
            "promo.update",
            extra={"promo_id": promo.id, "code": promo.code, "changes": changes},
        )
    await session.commit()
    await session.refresh(promo)
    return AdminPromo.model_validate(promo)


@router.get(
    "/{promo_id}/activations",
    response_model=list[AdminPromoActivation],
)
async def list_activations(
    promo_id: int,
    session: DBSession,
    _: AdminDep,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
) -> list[AdminPromoActivation]:
    promo = await session.get(PromoCode, promo_id)
    if promo is None:
        raise NotFoundError("Promo not found", error_code="promo_not_found")

    res = await session.execute(
        select(PromoActivation)
        .where(PromoActivation.promo_id == promo_id)
        .order_by(PromoActivation.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = res.scalars().all()
    return [AdminPromoActivation.model_validate(r) for r in rows]
