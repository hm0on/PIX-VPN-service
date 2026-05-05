"""Admin Users endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import aliased

from app.core.exceptions import NotFoundError
from app.db.models.balance_transaction import BalanceTransaction
from app.db.models.outbox import OUTBOX_MSG_TEXT
from app.db.models.payment import Payment
from app.db.models.referral import Referral
from app.db.models.subscription import SUB_STATUS_ACTIVE, Subscription
from app.db.models.ticket import Ticket
from app.db.models.user import User
from app.deps import AdminDep, DBSession, NorthLineClientDep
from app.repositories.outbox_repo import OutboxRepository
from app.schemas.admin_panel.users import (
    AdminUserBalanceAdjustRequest,
    AdminUserBalanceAdjustResponse,
    AdminUserBalanceTxItem,
    AdminUserBanRequest,
    AdminUserDetail,
    AdminUserListItem,
    AdminUserPaymentItem,
    AdminUserReferrals,
    AdminUsersPage,
    AdminUserSubscriptionItem,
    AdminUserTicketItem,
    InvitedReferralItem,
)
from app.schemas.common import OkResponse
from app.services.audit_service import record_admin_action
from app.services.balance_service import BalanceService

router = APIRouter()


_SORT_FIELDS: dict[str, Any] = {
    "id": User.id,
    "tg_id": User.tg_id,
    "username": User.username,
    "balance": User.balance_kopecks,
    "balance_kop": User.balance_kopecks,
    "balance_kopecks": User.balance_kopecks,  # legacy alias
    "created_at": User.created_at,
}


def _parse_sort(sort: str | None):
    if not sort:
        return User.created_at.desc()
    desc = sort.startswith("-")
    name = sort[1:] if desc else sort
    col = _SORT_FIELDS.get(name)
    if col is None:
        return User.created_at.desc()
    return col.desc() if desc else col.asc()


@router.get("", response_model=AdminUsersPage)
async def list_users(
    session: DBSession,
    _: AdminDep,
    q: str | None = Query(None, description="Search tg_id / username / first_name"),
    banned: bool | None = Query(None),
    with_subscription: bool | None = Query(None),
    min_balance: int | None = Query(None, ge=0),
    sort: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
) -> AdminUsersPage:
    # Active subscription count (correlated subquery as scalar)
    active_count_subq = (
        select(func.count(Subscription.id))
        .where(
            Subscription.user_id == User.id,
            Subscription.status == SUB_STATUS_ACTIVE,
        )
        .correlate(User)
        .scalar_subquery()
    )

    base_filters: list[Any] = []
    if q:
        like = f"%{q}%"
        try:
            tg_id_int = int(q)
            id_match = or_(User.tg_id == tg_id_int)
        except ValueError:
            id_match = None
        clauses = [
            User.username.ilike(like),
            User.first_name.ilike(like),
            User.last_name.ilike(like),
        ]
        if id_match is not None:
            clauses.append(id_match)  # type: ignore[arg-type]  # type: ignore[arg-type]
        base_filters.append(or_(*clauses))
    if banned is not None:
        base_filters.append(User.is_banned.is_(banned))
    if min_balance is not None:
        base_filters.append(User.balance_kopecks >= int(min_balance))

    if with_subscription is True:
        base_filters.append(active_count_subq > 0)
    elif with_subscription is False:
        base_filters.append(active_count_subq == 0)

    where_clause = and_(*base_filters) if base_filters else None

    # total
    count_stmt = select(func.count()).select_from(User)
    if where_clause is not None:
        count_stmt = count_stmt.where(where_clause)
    total = int((await session.execute(count_stmt)).scalar_one())

    # items
    stmt = select(User, active_count_subq.label("active_cnt"))
    if where_clause is not None:
        stmt = stmt.where(where_clause)
    stmt = stmt.order_by(_parse_sort(sort)).limit(page_size).offset((page - 1) * page_size)

    rows = (await session.execute(stmt)).all()
    items = [
        AdminUserListItem(
            id=u.id,
            tg_id=u.tg_id,
            username=u.username,
            first_name=u.first_name,
            last_name=u.last_name,
            balance_kop=int(u.balance_kopecks),
            active_subscriptions_count=int(cnt or 0),
            is_banned=bool(u.is_banned),
            ban_reason=u.banned_reason,
            created_at=u.created_at,
        )
        for u, cnt in rows
    ]
    return AdminUsersPage(items=items, total=total, page=page, page_size=page_size)


async def _get_user_or_404(session, user_id: int) -> User:  # noqa: ANN001
    res = await session.execute(select(User).where(User.id == user_id))
    user = res.scalar_one_or_none()
    if user is None:
        raise NotFoundError(
            f"User id={user_id} not found", error_code="user_not_found"
        )
    return user


@router.get("/{user_id}", response_model=AdminUserDetail)
async def get_user_detail(
    user_id: int,
    session: DBSession,
    _: AdminDep,
) -> AdminUserDetail:
    user = await _get_user_or_404(session, user_id)

    referrer_payload: dict[str, Any] | None = None
    if user.ref_id:
        ref_res = await session.execute(select(User).where(User.id == user.ref_id))
        ref_user = ref_res.scalar_one_or_none()
        if ref_user is not None:
            referrer_payload = {
                "id": ref_user.id,
                "tg_id": ref_user.tg_id,
                "username": ref_user.username,
                "first_name": ref_user.first_name,
            }
    return AdminUserDetail(
        id=user.id,
        tg_id=user.tg_id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        language_code=user.language_code,
        balance_kop=int(user.balance_kopecks),
        is_banned=bool(user.is_banned),
        ban_reason=user.banned_reason,
        created_at=user.created_at,
        referrer=referrer_payload,
    )


@router.get("/{user_id}/payments", response_model=list[AdminUserPaymentItem])
async def list_user_payments(
    user_id: int,
    session: DBSession,
    _: AdminDep,
) -> list[AdminUserPaymentItem]:
    await _get_user_or_404(session, user_id)
    stmt = (
        select(Payment)
        .where(Payment.user_id == user_id)
        .order_by(Payment.created_at.desc())
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [
        AdminUserPaymentItem(
            id=p.id,
            subscription_id=p.subscription_id,
            purpose=p.purpose,
            provider=p.provider,
            amount_kop=int(p.amount_kopecks),
            currency=p.currency,
            status=p.status,
            created_at=p.created_at,
            paid_at=p.paid_at,
        )
        for p in rows
    ]


@router.get("/{user_id}/subscriptions", response_model=list[AdminUserSubscriptionItem])
async def list_user_subscriptions(
    user_id: int,
    session: DBSession,
    _: AdminDep,
) -> list[AdminUserSubscriptionItem]:
    await _get_user_or_404(session, user_id)
    stmt = (
        select(Subscription)
        .where(Subscription.user_id == user_id)
        .order_by(Subscription.created_at.desc())
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [
        AdminUserSubscriptionItem(
            id=s.id,
            tariff_id=s.tariff_id,
            devices=s.devices,
            days=s.days,
            status=s.status,
            is_free_trial=bool(s.is_free_trial),
            started_at=s.started_at,
            expires_at=s.expires_at,
            deactivated_at=s.deactivated_at,
            deactivation_reason=s.deactivation_reason,
            key_url=s.key_url,
            created_at=s.created_at,
        )
        for s in rows
    ]


@router.get("/{user_id}/tickets", response_model=list[AdminUserTicketItem])
async def list_user_tickets(
    user_id: int,
    session: DBSession,
    _: AdminDep,
) -> list[AdminUserTicketItem]:
    await _get_user_or_404(session, user_id)
    stmt = (
        select(Ticket)
        .where(Ticket.user_id == user_id)
        .order_by(Ticket.created_at.desc())
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [
        AdminUserTicketItem(
            id=t.id,
            code=t.code,
            kind=t.kind,
            status=t.status,
            closed_by=t.closed_by,
            created_at=t.created_at,
            closed_at=t.closed_at,
        )
        for t in rows
    ]


@router.get("/{user_id}/referrals", response_model=AdminUserReferrals)
async def get_user_referrals(
    user_id: int,
    session: DBSession,
    _: AdminDep,
) -> AdminUserReferrals:
    user = await _get_user_or_404(session, user_id)

    # Referrer
    referrer_payload: dict[str, Any] | None = None
    if user.ref_id:
        res = await session.execute(select(User).where(User.id == user.ref_id))
        ref_user = res.scalar_one_or_none()
        if ref_user is not None:
            referrer_payload = {
                "id": ref_user.id,
                "tg_id": ref_user.tg_id,
                "username": ref_user.username,
                "first_name": ref_user.first_name,
            }

    # Invited (this user as referrer in `referrals`)
    invitee_alias = aliased(User)
    stmt = (
        select(Referral, invitee_alias)
        .join(invitee_alias, invitee_alias.id == Referral.referee_id)
        .where(Referral.referrer_id == user_id)
        .order_by(Referral.created_at.desc())
    )
    rows = (await session.execute(stmt)).all()
    invited_items: list[InvitedReferralItem] = []
    for ref, invitee in rows:
        invited_items.append(
            InvitedReferralItem(
                user={
                    "id": invitee.id,
                    "tg_id": invitee.tg_id,
                    "username": invitee.username,
                    "first_name": invitee.first_name,
                    "created_at": invitee.created_at,
                },
                paid=bool(ref.bonus_paid),
                bonus_paid_at=ref.bonus_paid_at,
            )
        )

    return AdminUserReferrals(referrer=referrer_payload, invited=invited_items)


@router.get("/{user_id}/balance-history", response_model=list[AdminUserBalanceTxItem])
async def get_user_balance_history(
    user_id: int,
    session: DBSession,
    _: AdminDep,
) -> list[AdminUserBalanceTxItem]:
    await _get_user_or_404(session, user_id)
    stmt = (
        select(BalanceTransaction)
        .where(BalanceTransaction.user_id == user_id)
        .order_by(BalanceTransaction.created_at.desc())
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [
        AdminUserBalanceTxItem(
            id=t.id,
            amount_kop=int(t.amount_kopecks),
            reason=t.reason,
            description=t.description,
            balance_after_kop=int(t.balance_after_kopecks),
            ref_payment_id=t.ref_payment_id,
            ref_subscription_id=t.ref_subscription_id,
            created_at=t.created_at,
        )
        for t in rows
    ]


# ---------- mutating endpoints ----------


def _kopecks_to_rub_str(kopecks: int) -> str:
    sign = "-" if kopecks < 0 else "+"
    return f"{sign}{abs(kopecks) / 100:.2f}"


@router.post("/{user_id}/ban", response_model=OkResponse)
async def ban_user(
    user_id: int,
    payload: AdminUserBanRequest,
    session: DBSession,
    admin: AdminDep,
) -> OkResponse:
    user = await _get_user_or_404(session, user_id)
    user.is_banned = True
    user.banned_reason = payload.reason
    await session.flush()

    # Outbox: notify the user.
    outbox = OutboxRepository(session)
    await outbox.enqueue(
        user_id=user.id,
        chat_id=user.tg_id,
        message_type=OUTBOX_MSG_TEXT,
        payload={
            "text_key": "support_user_banned_notice",
            "format_kwargs": {"reason": payload.reason},
            "parse_mode": "HTML",
        },
    )

    await record_admin_action(
        session,
        admin,
        action="user.ban",
        target_user_id=user.id,
        extra={"reason": payload.reason},
    )
    await session.commit()
    return OkResponse(ok=True)


@router.post("/{user_id}/unban", response_model=OkResponse)
async def unban_user(
    user_id: int,
    session: DBSession,
    admin: AdminDep,
) -> OkResponse:
    user = await _get_user_or_404(session, user_id)
    user.is_banned = False
    user.banned_reason = None
    await session.flush()

    outbox = OutboxRepository(session)
    await outbox.enqueue(
        user_id=user.id,
        chat_id=user.tg_id,
        message_type=OUTBOX_MSG_TEXT,
        payload={
            "text_key": "support_user_unbanned_notice",
            "format_kwargs": {},
            "parse_mode": "HTML",
        },
    )

    await record_admin_action(
        session,
        admin,
        action="user.unban",
        target_user_id=user.id,
    )
    await session.commit()
    return OkResponse(ok=True)


@router.post(
    "/{user_id}/balance/adjust",
    response_model=AdminUserBalanceAdjustResponse,
)
async def adjust_balance(
    user_id: int,
    payload: AdminUserBalanceAdjustRequest,
    session: DBSession,
    admin: AdminDep,
    northline: NorthLineClientDep,
) -> AdminUserBalanceAdjustResponse:
    user = await _get_user_or_404(session, user_id)

    service = BalanceService(session, northline)
    delta_kopecks = int(payload.amount_kop)
    new_balance = await service.add_admin_adjust(
        user_id=user.id,
        amount_kopecks=delta_kopecks,
        reason=payload.reason,
        admin_key_id=admin.kid,
        admin_key_label=admin.label,
    )

    # Outbox: notify the user with delta + new balance (rubles).
    outbox = OutboxRepository(session)
    await outbox.enqueue(
        user_id=user.id,
        chat_id=user.tg_id,
        message_type=OUTBOX_MSG_TEXT,
        payload={
            "text_key": "balance_admin_adjusted",
            "format_kwargs": {
                "delta": _kopecks_to_rub_str(delta_kopecks),
                "balance": f"{new_balance / 100:.2f}",
                "reason": payload.reason,
            },
            "parse_mode": "HTML",
        },
    )

    await record_admin_action(
        session,
        admin,
        action="user.balance.adjust",
        target_user_id=user.id,
        extra={
            "amount_kopecks": delta_kopecks,
            "balance_after_kopecks": new_balance,
            "reason": payload.reason,
        },
    )
    await session.commit()
    return AdminUserBalanceAdjustResponse(
        user_id=user.id,
        balance_kop=new_balance,
        delta_kop=delta_kopecks,
    )


# Mark unused import ok for linters that catch it
_ = datetime, timezone  # noqa
