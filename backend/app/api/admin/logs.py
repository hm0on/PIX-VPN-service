"""Admin Logs router (Stage 5).

Cursor-based pagination over `logs` and `tech_logs`. SSE stream over `logs`
polls the DB for newly inserted rows every ~2 seconds.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import aliased

from app.core.exceptions import NotFoundError
from app.db.models.log import Log, TechLog
from app.db.models.user import User
from app.deps import AdminDep, DBSession
from app.schemas.admin_panel.log import (
    AdminLogItem,
    AdminLogsPage,
    AdminTechLogItem,
    AdminTechLogsPage,
)

router = APIRouter()


_DEFAULT_PAGE_SIZE = 100
_MAX_PAGE_SIZE = 500


def _parse_levels(level: list[str] | None) -> list[int]:
    """Map level strings (info/warning/critical) → ints."""
    if not level:
        return []
    mapping = {
        "info": 0,
        "warn": 1,
        "warning": 1,
        "critical": 2,
        "error": 2,
        "0": 0,
        "1": 1,
        "2": 2,
    }
    out: set[int] = set()
    for raw in level:
        v = mapping.get(raw.lower().strip())
        if v is not None:
            out.add(v)
    return sorted(out)


# --------------------------------------------------------------------- #
# Business logs
# --------------------------------------------------------------------- #
@router.get("/events", response_model=AdminLogsPage)
async def list_events(
    session: DBSession,
    _: AdminDep,
    level: list[str] | None = Query(default=None),
    module: str | None = Query(default=None, max_length=64),
    event: str | None = Query(default=None, max_length=128),
    user_q: str | None = Query(default=None, max_length=64),
    q: str | None = Query(default=None, max_length=200),
    from_ts: datetime | None = Query(default=None, alias="from"),
    to_ts: datetime | None = Query(default=None, alias="to"),
    before_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=_DEFAULT_PAGE_SIZE, ge=1, le=_MAX_PAGE_SIZE),
) -> AdminLogsPage:
    stmt = select(Log)

    levels = _parse_levels(level)
    if levels:
        stmt = stmt.where(Log.level.in_(levels))
    if module:
        stmt = stmt.where(Log.module == module)
    if event:
        stmt = stmt.where(Log.event == event)
    if from_ts is not None:
        stmt = stmt.where(Log.created_at >= from_ts)
    if to_ts is not None:
        stmt = stmt.where(Log.created_at <= to_ts)
    if q:
        stmt = stmt.where(Log.message.ilike(f"%{q}%"))
    if user_q:
        # Try by tg_id (digits) or by username substring.
        u = aliased(User)
        stmt = stmt.join(u, u.id == Log.user_id)
        if user_q.isdigit():
            stmt = stmt.where(
                or_(u.tg_id == int(user_q), u.username.ilike(f"%{user_q}%"))
            )
        else:
            stmt = stmt.where(
                or_(
                    u.username.ilike(f"%{user_q}%"),
                    u.first_name.ilike(f"%{user_q}%"),
                )
            )
    if before_id is not None:
        stmt = stmt.where(Log.id < before_id)

    stmt = stmt.order_by(Log.id.desc()).limit(limit + 1)
    res = await session.execute(stmt)
    rows = list(res.scalars().all())

    next_before_id: int | None = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_before_id = rows[-1].id

    return AdminLogsPage(
        items=[AdminLogItem.model_validate(r) for r in rows],
        next_before_id=next_before_id,
    )


@router.get("/events/stream")
async def stream_events(
    request: Request,
    session: DBSession,
    _: AdminDep,
) -> StreamingResponse:
    """Server-Sent Events stream of newly inserted log rows."""

    # Determine starting cursor: "now" — only show new rows after subscription.
    res = await session.execute(select(Log.id).order_by(Log.id.desc()).limit(1))
    last_id = int(res.scalar() or 0)

    async def _gen() -> AsyncIterator[bytes]:
        nonlocal last_id
        # Initial keepalive
        yield b": ok\n\n"
        try:
            while True:
                if await request.is_disconnected():
                    return

                rows_res = await session.execute(
                    select(Log)
                    .where(Log.id > last_id)
                    .order_by(Log.id.asc())
                    .limit(100)
                )
                rows = list(rows_res.scalars().all())
                for row in rows:
                    payload: dict[str, Any] = AdminLogItem.model_validate(
                        row
                    ).model_dump(mode="json")
                    line = (
                        f"event: log\n"
                        f"id: {row.id}\n"
                        f"data: {json.dumps(payload, default=str)}\n\n"
                    ).encode()
                    yield line
                    last_id = row.id

                # Heartbeat keeps the connection through nginx idle timeout.
                yield b": keepalive\n\n"
                await asyncio.sleep(2.0)
        except asyncio.CancelledError:
            return

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# --------------------------------------------------------------------- #
# Technical logs
# --------------------------------------------------------------------- #
@router.get("/tech", response_model=AdminTechLogsPage)
async def list_tech(
    session: DBSession,
    _: AdminDep,
    trace_id: str | None = Query(default=None, max_length=36),
    service: str | None = Query(default=None, max_length=32),
    action: str | None = Query(default=None, max_length=128),
    user_id: int | None = Query(default=None),
    from_ts: datetime | None = Query(default=None, alias="from"),
    to_ts: datetime | None = Query(default=None, alias="to"),
    before_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=_DEFAULT_PAGE_SIZE, ge=1, le=_MAX_PAGE_SIZE),
) -> AdminTechLogsPage:
    stmt = select(TechLog)
    if trace_id:
        stmt = stmt.where(TechLog.trace_id == trace_id)
    if service:
        stmt = stmt.where(TechLog.service == service)
    if action:
        stmt = stmt.where(TechLog.action == action)
    if user_id is not None:
        stmt = stmt.where(TechLog.user_id == user_id)
    if from_ts is not None:
        stmt = stmt.where(TechLog.created_at >= from_ts)
    if to_ts is not None:
        stmt = stmt.where(TechLog.created_at <= to_ts)
    if before_id is not None:
        stmt = stmt.where(TechLog.id < before_id)

    stmt = stmt.order_by(TechLog.id.desc()).limit(limit + 1)
    res = await session.execute(stmt)
    rows = list(res.scalars().all())

    next_before_id: int | None = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_before_id = rows[-1].id

    return AdminTechLogsPage(
        items=[AdminTechLogItem.model_validate(r) for r in rows],
        next_before_id=next_before_id,
    )


@router.get(
    "/tech/trace/{trace_id}",
    response_model=list[AdminTechLogItem],
)
async def get_trace(
    trace_id: str,
    session: DBSession,
    _: AdminDep,
) -> list[AdminTechLogItem]:
    res = await session.execute(
        select(TechLog)
        .where(TechLog.trace_id == trace_id)
        .order_by(TechLog.created_at.asc(), TechLog.id.asc())
    )
    rows = list(res.scalars().all())
    if not rows:
        raise NotFoundError(
            f"Trace '{trace_id}' not found",
            error_code="trace_not_found",
        )
    return [AdminTechLogItem.model_validate(r) for r in rows]
