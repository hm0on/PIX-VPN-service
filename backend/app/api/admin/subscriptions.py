"""Admin Subscriptions endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import and_, func, or_, select

from app.core.exceptions import (
    AppError,
    NorthLineClientError,
    NorthLineUnavailableError,
    NotFoundError,
    SubscriptionNotFoundError,
)
from app.db.models.outbox import OUTBOX_MSG_TEXT
from app.db.models.subscription import (
    SUB_STATUS_DEACTIVATED,
    Subscription,
)
from app.db.models.tariff import Tariff
from app.db.models.user import User
from app.deps import AdminDep, DBSession, NorthLineClientDep
from app.repositories.outbox_repo import OutboxRepository
from app.schemas.admin_panel.subscriptions import (
    AdminSubBrandingRequest,
    AdminSubDeactivateRequest,
    AdminSubDeactivateResponse,
    AdminSubDetail,
    AdminSubInfoResponse,
    AdminSubListItem,
    AdminSubReconcileResponse,
    AdminSubsPage,
)
from app.schemas.common import OkResponse
from app.services.audit_service import record_admin_action

router = APIRouter()


async def _get_sub_or_404(session, sub_id: int) -> Subscription:  # noqa: ANN001
    res = await session.execute(
        select(Subscription).where(Subscription.id == sub_id)
    )
    sub = res.scalar_one_or_none()
    if sub is None:
        raise SubscriptionNotFoundError(
            f"Subscription id={sub_id} not found",
            error_code="subscription_not_found",
        )
    return sub


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@router.get("", response_model=AdminSubsPage)
async def list_subscriptions(
    session: DBSession,
    _: AdminDep,
    status: str | None = Query(None),
    tariff_id: int | None = Query(None, ge=1),
    is_free_trial: bool | None = Query(None),
    expires_from: str | None = Query(None, description="ISO datetime"),
    expires_to: str | None = Query(None, description="ISO datetime"),
    q: str | None = Query(None, description="Search by key, sub id, user tg/username"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
) -> AdminSubsPage:
    filters: list[Any] = []

    if status:
        filters.append(Subscription.status == status)
    if tariff_id is not None:
        filters.append(Subscription.tariff_id == tariff_id)
    if is_free_trial is not None:
        filters.append(Subscription.is_free_trial.is_(is_free_trial))

    exp_from = _parse_dt(expires_from)
    exp_to = _parse_dt(expires_to)
    if exp_from is not None:
        filters.append(Subscription.expires_at >= exp_from)
    if exp_to is not None:
        filters.append(Subscription.expires_at <= exp_to)

    join_user = False
    if q:
        like = f"%{q}%"
        clauses = [Subscription.key_url.ilike(like)]
        try:
            sub_id_int = int(q)
            clauses.append(Subscription.id == sub_id_int)  # type: ignore[arg-type]
            clauses.append(User.tg_id == sub_id_int)  # type: ignore[arg-type]
        except ValueError:
            pass
        clauses.extend(
            [
                User.username.ilike(like),
                User.first_name.ilike(like),
            ]
        )
        filters.append(or_(*clauses))
        join_user = True

    where_clause = and_(*filters) if filters else None

    count_stmt = select(func.count()).select_from(Subscription)
    if join_user:
        count_stmt = count_stmt.join(User, User.id == Subscription.user_id)
    if where_clause is not None:
        count_stmt = count_stmt.where(where_clause)
    total = int((await session.execute(count_stmt)).scalar_one())

    # LEFT-OUTER-JOIN on Tariff so we can render ``tariff_name`` /
    # ``tariff_code`` straight from the list query — keeps the table view a
    # single round-trip instead of forcing the admin UI to hydrate tariffs
    # separately. We use OUTER so a deleted tariff (extremely rare with the
    # RESTRICT FK) doesn't make the row disappear from the listing.
    stmt = select(
        Subscription,
        User.tg_id,
        User.username,
        Tariff.name,
        Tariff.code,
    ).join(User, User.id == Subscription.user_id).outerjoin(
        Tariff, Tariff.id == Subscription.tariff_id
    )
    if where_clause is not None:
        stmt = stmt.where(where_clause)
    stmt = (
        stmt.order_by(Subscription.created_at.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    rows = (await session.execute(stmt)).all()
    items = [
        AdminSubListItem(
            id=s.id,
            user_id=s.user_id,
            user_tg_id=tg_id,
            user_username=username,
            tariff_id=s.tariff_id,
            tariff_code=tariff_code,
            tariff_name=tariff_name,
            devices=s.devices,
            days=s.days,
            status=s.status,
            is_free_trial=bool(s.is_free_trial),
            key_url=s.key_url,
            expires_at=s.expires_at,
            created_at=s.created_at,
        )
        for s, tg_id, username, tariff_name, tariff_code in rows
    ]
    return AdminSubsPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/{sub_id}", response_model=AdminSubDetail)
async def get_subscription(
    sub_id: int,
    session: DBSession,
    _: AdminDep,
) -> AdminSubDetail:
    sub = await _get_sub_or_404(session, sub_id)
    user_res = await session.execute(select(User).where(User.id == sub.user_id))
    user = user_res.scalar_one_or_none()
    # Single-row tariff lookup — cheap (PK index) and keeps the detail
    # response self-contained so the UI doesn't need a separate tariffs fetch.
    tariff_res = await session.execute(
        select(Tariff.name, Tariff.code).where(Tariff.id == sub.tariff_id)
    )
    tariff_row = tariff_res.first()
    tariff_name = tariff_row[0] if tariff_row else None
    tariff_code = tariff_row[1] if tariff_row else None
    return AdminSubDetail(
        id=sub.id,
        user_id=sub.user_id,
        user_tg_id=(user.tg_id if user else None),
        user_username=(user.username if user else None),
        tariff_id=sub.tariff_id,
        tariff_code=tariff_code,
        tariff_name=tariff_name,
        tariff_duration_id=sub.tariff_duration_id,
        provider_subscription_id=sub.provider_subscription_id,
        key_url=sub.key_url,
        devices=sub.devices,
        days=sub.days,
        status=sub.status,
        is_free_trial=bool(sub.is_free_trial),
        started_at=sub.started_at,
        expires_at=sub.expires_at,
        deactivated_at=sub.deactivated_at,
        deactivation_reason=sub.deactivation_reason,
        created_at=sub.created_at,
    )


@router.get("/{sub_id}/info", response_model=AdminSubInfoResponse)
async def get_subscription_info(
    sub_id: int,
    session: DBSession,
    _: AdminDep,
    northline: NorthLineClientDep,
) -> AdminSubInfoResponse:
    sub = await _get_sub_or_404(session, sub_id)
    if not sub.provider_subscription_id:
        raise NotFoundError(
            "Subscription has no NorthLine key id",
            error_code="provider_subscription_id_missing",
        )
    try:
        info = await northline.get_key(subscription_id=sub.provider_subscription_id)
    except (NorthLineClientError, NorthLineUnavailableError) as e:
        # Translate to 502 with a friendly payload via existing AppError pipeline.
        raise NorthLineUnavailableError(
            "Could not fetch key info from NorthLine",
            details={
                "subscription_id": sub.id,
                "error_code": getattr(e, "error_code", None),
                "error_message": getattr(e, "message", None),
            },
        ) from e

    # Adapt the NorthLine ``KeyDevice`` payload to the keys the admin UI
    # expects (``id`` / ``last_seen_at`` instead of ``device_id`` /
    # ``last_seen``). Fields the upstream doesn't supply (``ip``, ``platform``)
    # are passed through as ``None`` so the table can render ``—``. NorthLine
    # currently returns an empty list, but normalising here means the UI
    # works the moment the upstream flips it on.
    devices_payload: list[dict[str, Any]] = []
    for d in info.devices:
        dump = d.model_dump(mode="json")
        devices_payload.append(
            {
                "id": dump.get("device_id"),
                "name": dump.get("name"),
                "platform": dump.get("platform"),
                "last_seen_at": dump.get("last_seen"),
                "ip": dump.get("ip"),
                "traffic_bytes": dump.get("traffic_bytes"),
            }
        )

    # NorthLine spec: ``traffic_quota_gb == -1`` means unlimited. Surface
    # as a flag so the UI doesn't have to interpret a magic int.
    unlimited = info.traffic_quota_gb is not None and info.traffic_quota_gb < 0

    return AdminSubInfoResponse(
        provider_status=info.status,
        traffic_bytes=info.traffic_bytes,
        traffic_quota_gb=info.traffic_quota_gb,
        unlimited_traffic=unlimited,
        lte_traffic_bytes=info.lte_traffic_bytes,
        devices_total=info.devices_total,
        devices_used=info.devices_used,
        expires_at=info.expires_at,
        devices=devices_payload,
        raw=info.model_dump(mode="json"),
    )


@router.post("/{sub_id}/deactivate", response_model=AdminSubDeactivateResponse)
async def deactivate_subscription(
    sub_id: int,
    payload: AdminSubDeactivateRequest,
    session: DBSession,
    admin: AdminDep,
    northline: NorthLineClientDep,
) -> AdminSubDeactivateResponse:
    sub = await _get_sub_or_404(session, sub_id)

    # Best-effort NorthLine call; on hard failure, surface 502 (don't mark in DB).
    if sub.provider_subscription_id:
        try:
            await northline.deactivate_key(
                subscription_id=sub.provider_subscription_id,
                reason=payload.reason,
            )
        except NorthLineClientError as e:
            # 4xx from NorthLine: re-raise as AppError (mapped to 502 by handler).
            raise e
        except NorthLineUnavailableError as e:
            raise e

    now = datetime.now(tz=UTC)
    sub.status = SUB_STATUS_DEACTIVATED
    sub.deactivated_at = now
    sub.deactivation_reason = payload.reason
    await session.flush()

    # Notify the user.
    user_res = await session.execute(select(User).where(User.id == sub.user_id))
    user = user_res.scalar_one_or_none()
    if user is not None:
        outbox = OutboxRepository(session)
        await outbox.enqueue(
            user_id=user.id,
            chat_id=user.tg_id,
            message_type=OUTBOX_MSG_TEXT,
            payload={
                "text_key": "subscription_deactivated_by_admin",
                "format_kwargs": {
                    "key_id": sub.id,
                    "reason": payload.reason,
                },
                "parse_mode": "HTML",
            },
        )

    await record_admin_action(
        session,
        admin,
        action="subscription.deactivate",
        target_user_id=sub.user_id,
        target_subscription_id=sub.id,
        extra={"reason": payload.reason},
    )
    await session.commit()

    return AdminSubDeactivateResponse(
        id=sub.id,
        status=sub.status,
        deactivated_at=sub.deactivated_at,
        deactivation_reason=sub.deactivation_reason,
    )


@router.delete("/{sub_id}/devices/{device_id}", response_model=OkResponse)
async def remove_subscription_device(
    sub_id: int,
    device_id: str,
    session: DBSession,
    admin: AdminDep,
    northline: NorthLineClientDep,
) -> OkResponse:
    sub = await _get_sub_or_404(session, sub_id)
    if not sub.provider_subscription_id:
        raise NotFoundError(
            "Subscription has no NorthLine key id",
            error_code="provider_subscription_id_missing",
        )

    try:
        await northline.remove_device(
            subscription_id=sub.provider_subscription_id,
            device_id=device_id,
        )
    except (NorthLineClientError, NorthLineUnavailableError) as e:
        # Bubble up as AppError (already mapped to 502/4xx).
        raise e

    await record_admin_action(
        session,
        admin,
        action="subscription.device.remove",
        target_user_id=sub.user_id,
        target_subscription_id=sub.id,
        extra={"device_id": device_id},
    )
    await session.commit()
    return OkResponse(ok=True)


@router.put("/{sub_id}/branding", response_model=OkResponse)
async def set_subscription_branding(
    sub_id: int,
    payload: AdminSubBrandingRequest,
    session: DBSession,
    admin: AdminDep,
    northline: NorthLineClientDep,
) -> OkResponse:
    """Per-subscription branding override.

    Sends ``PATCH /keys/{provider_id}/branding`` to NorthLine. Empty
    payloads are rejected with 400 — the upstream already complains, but
    we'd rather fail fast than burn a request.
    """
    sub = await _get_sub_or_404(session, sub_id)
    if not sub.provider_subscription_id:
        raise NotFoundError(
            "Subscription has no NorthLine key id",
            error_code="provider_subscription_id_missing",
        )

    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        raise NorthLineClientError(
            error_code="empty_payload",
            error_message="Branding override requires at least one field",
            http_status=400,
        )

    try:
        await northline.set_subscription_branding(
            subscription_id=sub.provider_subscription_id,
            **fields,
        )
    except (NorthLineClientError, NorthLineUnavailableError):
        raise

    await record_admin_action(
        session,
        admin,
        action="subscription.branding.update",
        target_user_id=sub.user_id,
        target_subscription_id=sub.id,
        extra={"fields": sorted(fields.keys())},
    )
    await session.commit()
    return OkResponse(ok=True)


@router.post("/{sub_id}/reconcile", response_model=AdminSubReconcileResponse)
async def reconcile_subscription(
    sub_id: int,
    session: DBSession,
    admin: AdminDep,
    northline: NorthLineClientDep,
) -> AdminSubReconcileResponse:
    """Force-reconcile a single subscription against NorthLine.

    Mirrors the per-row logic of
    :func:`app.services.subscription_reconcile_service.reconcile_subscriptions`
    but for one ID, so the admin can resolve drift on demand without
    waiting for the cron. We deliberately don't import the batch function
    — it's batch-shaped (skips test rows silently, swallows per-row
    errors) and what the admin wants here is the verdict, not a counter.
    """
    from app.db.models.subscription import (
        SUB_STATUS_DEACTIVATED,
        SUB_STATUS_EXPIRED,
    )
    from app.services.subscription_reconcile_service import (
        DRIFT_THRESHOLD,
        _ensure_utc,
        _is_test_subscription_id,
    )

    sub = await _get_sub_or_404(session, sub_id)
    old_status = sub.status
    old_expires_at = sub.expires_at

    if not sub.provider_subscription_id:
        raise NotFoundError(
            "Subscription has no NorthLine key id",
            error_code="provider_subscription_id_missing",
        )
    if _is_test_subscription_id(sub.provider_subscription_id):
        return AdminSubReconcileResponse(
            subscription_id=sub.id,
            action="skipped_test",
            old_status=old_status,
            new_status=old_status,
            old_expires_at=old_expires_at,
            new_expires_at=old_expires_at,
            message="Test-mode subscription — provider does not track it.",
        )

    now = datetime.now(tz=UTC)
    try:
        info = await northline.get_key(
            subscription_id=str(sub.provider_subscription_id)
        )
    except NorthLineClientError as exc:
        if (exc.error_code or "").lower() in {"invalid_provider_key", "not_found"}:
            sub.status = SUB_STATUS_DEACTIVATED
            sub.deactivated_at = now
            sub.deactivation_reason = (
                f"Reconcile (admin): provider returned {exc.error_code}"
            )
            await session.commit()
            return AdminSubReconcileResponse(
                subscription_id=sub.id,
                action="provider_unknown_key",
                old_status=old_status,
                new_status=sub.status,
                old_expires_at=old_expires_at,
                new_expires_at=sub.expires_at,
                message=(
                    f"Provider does not know subscription "
                    f"{sub.provider_subscription_id}; marked deactivated."
                ),
            )
        raise

    provider_status = (info.status or "").lower()
    if provider_status and provider_status != "active":
        new_status = (
            SUB_STATUS_DEACTIVATED
            if provider_status == "suspended"
            else SUB_STATUS_EXPIRED
        )
        sub.status = new_status
        if new_status == SUB_STATUS_DEACTIVATED:
            sub.deactivated_at = now
            sub.deactivation_reason = (
                f"Reconcile (admin): provider status={provider_status}"
            )
        await record_admin_action(
            session,
            admin,
            action="subscription.reconcile.flip",
            target_user_id=sub.user_id,
            target_subscription_id=sub.id,
            extra={
                "provider_status": provider_status,
                "new_local_status": new_status,
            },
        )
        await session.commit()
        return AdminSubReconcileResponse(
            subscription_id=sub.id,
            action="status_flipped",
            old_status=old_status,
            new_status=new_status,
            old_expires_at=old_expires_at,
            new_expires_at=sub.expires_at,
            provider_status=info.status,
            message=(
                f"Status drift: local=active provider={provider_status} "
                f"→ {new_status}."
            ),
        )

    provider_exp = _ensure_utc(info.expires_at)
    local_exp = _ensure_utc(sub.expires_at)
    if provider_exp is None or local_exp is None:
        return AdminSubReconcileResponse(
            subscription_id=sub.id,
            action="no_change",
            old_status=old_status,
            new_status=old_status,
            old_expires_at=old_expires_at,
            new_expires_at=old_expires_at,
            provider_status=info.status,
            message="No expires_at on one side; nothing to reconcile.",
        )

    delta = provider_exp - local_exp
    if delta > DRIFT_THRESHOLD:
        sub.expires_at = provider_exp
        await record_admin_action(
            session,
            admin,
            action="subscription.reconcile.extend",
            target_user_id=sub.user_id,
            target_subscription_id=sub.id,
            extra={
                "old_expires_at": local_exp.isoformat(),
                "new_expires_at": provider_exp.isoformat(),
            },
        )
        await session.commit()
        return AdminSubReconcileResponse(
            subscription_id=sub.id,
            action="expires_extended",
            old_status=old_status,
            new_status=old_status,
            old_expires_at=local_exp,
            new_expires_at=provider_exp,
            provider_status=info.status,
            message=(
                f"expires_at pulled forward "
                f"{local_exp.isoformat()} → {provider_exp.isoformat()}."
            ),
        )
    if -delta > DRIFT_THRESHOLD:
        # Don't shorten silently — that destroys paid time.
        return AdminSubReconcileResponse(
            subscription_id=sub.id,
            action="expires_shrink_warned",
            old_status=old_status,
            new_status=old_status,
            old_expires_at=local_exp,
            new_expires_at=local_exp,
            provider_status=info.status,
            message=(
                "Provider has earlier expires_at than local; not shortened "
                "automatically. Investigate manually if needed."
            ),
        )

    return AdminSubReconcileResponse(
        subscription_id=sub.id,
        action="no_change",
        old_status=old_status,
        new_status=old_status,
        old_expires_at=local_exp,
        new_expires_at=local_exp,
        provider_status=info.status,
        message="In sync.",
    )


# Compatibility silencer for unused imports
_ = AppError
