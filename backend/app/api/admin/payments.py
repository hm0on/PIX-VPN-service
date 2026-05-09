"""Admin Payments — global listing across all users.

Per-user listing already lives at ``/admin/users/{id}/payments``; this
router is for ops who need the full firehose: filter by status /
provider / date range, paginate, drill into a row.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import and_, func, or_, select

from app.db.models.payment import Payment
from app.db.models.user import User
from app.deps import AdminDep, DBSession
from app.schemas.admin_panel.payments import (
    AdminPaymentListItem,
    AdminPaymentsPage,
)

router = APIRouter()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@router.get("", response_model=AdminPaymentsPage)
async def list_payments(
    session: DBSession,
    _: AdminDep,
    status: str | None = Query(None, description="pending|paid|failed|expired|refunded"),
    provider: str | None = Query(
        None,
        description="platega_sbp|platega_crypto|cryptobot|balance",
    ),
    purpose: str | None = Query(None, description="subscription|topup"),
    user_id: int | None = Query(None, ge=1),
    created_from: str | None = Query(None, description="ISO datetime"),
    created_to: str | None = Query(None, description="ISO datetime"),
    q: str | None = Query(None, description="payment id, external id, user tg/username"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
) -> AdminPaymentsPage:
    filters: list[Any] = []
    if status:
        filters.append(Payment.status == status)
    if provider:
        filters.append(Payment.provider == provider)
    if purpose:
        filters.append(Payment.purpose == purpose)
    if user_id is not None:
        filters.append(Payment.user_id == user_id)

    cf = _parse_dt(created_from)
    ct = _parse_dt(created_to)
    if cf is not None:
        filters.append(Payment.created_at >= cf)
    if ct is not None:
        filters.append(Payment.created_at <= ct)

    join_user = False
    if q:
        like = f"%{q}%"
        clauses: list[Any] = [Payment.external_id.ilike(like)]
        try:
            n = int(q)
            clauses.append(Payment.id == n)
            clauses.append(User.tg_id == n)
        except ValueError:
            pass
        clauses.extend([User.username.ilike(like), User.first_name.ilike(like)])
        filters.append(or_(*clauses))
        join_user = True

    where_clause = and_(*filters) if filters else None

    count_stmt = select(func.count()).select_from(Payment)
    if join_user:
        count_stmt = count_stmt.join(User, User.id == Payment.user_id)
    if where_clause is not None:
        count_stmt = count_stmt.where(where_clause)
    total = int((await session.execute(count_stmt)).scalar_one())

    # Always join User for the listing — the admin table renders tg_id /
    # username inline. Cheap (PK index) and saves a round-trip.
    stmt = (
        select(Payment, User.tg_id, User.username)
        .join(User, User.id == Payment.user_id)
    )
    if where_clause is not None:
        stmt = stmt.where(where_clause)
    stmt = (
        stmt.order_by(Payment.created_at.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    rows = (await session.execute(stmt)).all()
    items = [
        AdminPaymentListItem(
            id=p.id,
            user_id=p.user_id,
            user_tg_id=tg_id,
            user_username=username,
            subscription_id=p.subscription_id,
            purpose=p.purpose,
            provider=p.provider,
            external_id=p.external_id,
            amount_kop=int(p.amount_kopecks),
            currency=p.currency,
            status=p.status,
            created_at=p.created_at,
            paid_at=p.paid_at,
        )
        for p, tg_id, username in rows
    ]
    return AdminPaymentsPage(items=items, total=total, page=page, page_size=page_size)
