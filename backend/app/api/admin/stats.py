"""Admin dashboard / stats endpoints.

Contract is consumed by the admin SPA (see `admin/src/api/endpoints/stats.ts`):
  * KPI fields:  users_total, users_delta_24h, active_subscriptions,
                 revenue_month_kop, revenue_today_kop
  * /revenue and /users return a flat array of points (no wrapper)
  * /recent-payments and /recent-users live at /admin/stats/recent-* (no
    `/dashboard/` prefix); recent payments expose `amount_kop`, `status`,
    `subscription_id`.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, func, select

try:  # sse-starlette is preferred; fall back to a manual stream if missing.
    from sse_starlette.sse import EventSourceResponse  # type: ignore[import-not-found]
except Exception:  # pragma: no cover  # noqa: BLE001
    EventSourceResponse = None  # type: ignore[assignment]

from app.db.models.payment import PAYMENT_STATUS_PAID, Payment
from app.db.models.subscription import SUB_STATUS_ACTIVE, Subscription
from app.db.models.user import User
from app.deps import DBSession
from app.schemas.admin_panel.stats import (
    DashboardKPIs,
    RecentPaymentItem,
    RecentUserItem,
    RevenuePoint,
    UsersPoint,
)

router = APIRouter()

PERIOD_DAYS = {"30d": 30, "90d": 90, "365d": 365}
Period = Literal["30d", "90d", "365d"]


# ---------- helpers ----------


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


async def _compute_kpis(session) -> DashboardKPIs:  # noqa: ANN001
    now = _utcnow()
    today_start = datetime(now.year, now.month, now.day, tzinfo=UTC)
    month_start = datetime(now.year, now.month, 1, tzinfo=UTC)
    yesterday = now - timedelta(hours=24)

    total_users_q = select(func.count(User.id))
    users_24h_q = select(func.count(User.id)).where(User.created_at >= yesterday)
    active_subs_q = select(func.count(Subscription.id)).where(
        Subscription.status == SUB_STATUS_ACTIVE
    )
    revenue_month_q = select(func.coalesce(func.sum(Payment.amount_kopecks), 0)).where(
        Payment.status == PAYMENT_STATUS_PAID,
        Payment.paid_at >= month_start,
    )
    revenue_today_q = select(func.coalesce(func.sum(Payment.amount_kopecks), 0)).where(
        Payment.status == PAYMENT_STATUS_PAID,
        Payment.paid_at >= today_start,
    )

    total_users = (await session.execute(total_users_q)).scalar_one() or 0
    users_24h = (await session.execute(users_24h_q)).scalar_one() or 0
    active_subs = (await session.execute(active_subs_q)).scalar_one() or 0
    revenue_month = int((await session.execute(revenue_month_q)).scalar_one() or 0)
    revenue_today = int((await session.execute(revenue_today_q)).scalar_one() or 0)

    return DashboardKPIs(
        users_total=int(total_users),
        users_delta_24h=int(users_24h),
        active_subscriptions=int(active_subs),
        revenue_month_kop=revenue_month,
        revenue_today_kop=revenue_today,
    )


def _date_iter(start: date, end: date):
    cur = start
    while cur <= end:
        yield cur
        cur = cur + timedelta(days=1)


# ---------- endpoints ----------


@router.get("/dashboard", response_model=DashboardKPIs)
async def dashboard(session: DBSession) -> DashboardKPIs:
    return await _compute_kpis(session)


@router.get("/revenue", response_model=list[RevenuePoint])
async def revenue(
    session: DBSession,
    period: Period = Query("30d"),
) -> list[RevenuePoint]:
    days = PERIOD_DAYS[period]
    end = _utcnow().date()
    start = end - timedelta(days=days - 1)
    start_dt = datetime(start.year, start.month, start.day, tzinfo=UTC)

    bucket = func.date(Payment.paid_at).label("d")
    stmt = (
        select(bucket, func.coalesce(func.sum(Payment.amount_kopecks), 0))
        .where(
            and_(
                Payment.status == PAYMENT_STATUS_PAID,
                Payment.paid_at >= start_dt,
            )
        )
        .group_by(bucket)
        .order_by(bucket)
    )
    rows = (await session.execute(stmt)).all()
    by_date: dict[str, int] = {}
    for d, total in rows:
        if d is None:
            continue
        if isinstance(d, datetime):
            key = d.date().isoformat()
        else:
            key = str(d)
        by_date[key] = int(total or 0)

    return [
        RevenuePoint(date=d.isoformat(), amount_kop=by_date.get(d.isoformat(), 0))
        for d in _date_iter(start, end)
    ]


@router.get("/users", response_model=list[UsersPoint])
async def users_timeseries(
    session: DBSession,
    period: Period = Query("30d"),
) -> list[UsersPoint]:
    days = PERIOD_DAYS[period]
    end = _utcnow().date()
    start = end - timedelta(days=days - 1)
    start_dt = datetime(start.year, start.month, start.day, tzinfo=UTC)

    bucket = func.date(User.created_at).label("d")
    stmt = (
        select(bucket, func.count(User.id))
        .where(User.created_at >= start_dt)
        .group_by(bucket)
        .order_by(bucket)
    )
    rows = (await session.execute(stmt)).all()
    by_date: dict[str, int] = {}
    for d, cnt in rows:
        if d is None:
            continue
        key = d.date().isoformat() if isinstance(d, datetime) else str(d)
        by_date[key] = int(cnt or 0)

    return [
        UsersPoint(date=d.isoformat(), count=by_date.get(d.isoformat(), 0))
        for d in _date_iter(start, end)
    ]


@router.get("/recent-payments", response_model=list[RecentPaymentItem])
async def recent_payments(
    session: DBSession,
    limit: int = Query(10, ge=1, le=100),
) -> list[RecentPaymentItem]:
    stmt = (
        select(Payment, User.tg_id, User.username)
        .join(User, User.id == Payment.user_id)
        .where(Payment.status == PAYMENT_STATUS_PAID)
        .order_by(Payment.paid_at.desc().nullslast(), Payment.created_at.desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    out: list[RecentPaymentItem] = []
    for p, tg_id, username in rows:
        out.append(
            RecentPaymentItem(
                id=p.id,
                user_id=p.user_id,
                user_tg_id=tg_id,
                user_username=username,
                amount_kop=int(p.amount_kopecks),
                provider=p.provider,
                status=p.status,
                subscription_id=getattr(p, "subscription_id", None),
                created_at=p.created_at,
                paid_at=p.paid_at,
            )
        )
    return out


@router.get("/recent-users", response_model=list[RecentUserItem])
async def recent_users(
    session: DBSession,
    limit: int = Query(10, ge=1, le=100),
) -> list[RecentUserItem]:
    stmt = select(User).order_by(User.created_at.desc()).limit(limit)
    rows = (await session.execute(stmt)).scalars().all()
    return [
        RecentUserItem(
            id=u.id,
            tg_id=u.tg_id,
            username=u.username,
            first_name=u.first_name,
            created_at=u.created_at,
        )
        for u in rows
    ]


# ---------- SSE ----------


@router.get("/stream")
async def stats_stream(session: DBSession):
    """Server-Sent Events: emits {type:'kpi', data: DashboardKPIs} every 30s.

    Uses ``sse_starlette.EventSourceResponse`` when available; falls back to a
    raw ``StreamingResponse`` so the route always works.
    """

    async def gen_payloads():
        try:
            while True:
                kpis = await _compute_kpis(session)
                yield json.dumps({"type": "kpi", "data": kpis.model_dump(mode="json")})
                await asyncio.sleep(30)
        except asyncio.CancelledError:  # pragma: no cover
            return

    if EventSourceResponse is not None:
        async def sse_gen():
            async for payload in gen_payloads():
                yield {"event": "kpi", "data": payload}

        return EventSourceResponse(sse_gen())

    async def raw_gen():
        async for payload in gen_payloads():
            yield f"event: kpi\ndata: {payload}\n\n"

    return StreamingResponse(
        raw_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
