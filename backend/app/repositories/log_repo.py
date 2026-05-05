"""Log / TechLog repository."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.log import Log, TechLog


class LogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_business(
        self,
        *,
        level: int,
        event: str,
        module: str,
        message: str,
        user_id: int | None = None,
        context: dict[str, Any] | None = None,
    ) -> Log:
        row = Log(
            level=level,
            event=event,
            module=module,
            user_id=user_id,
            message=message,
            context=context,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def add_tech(
        self,
        *,
        trace_id: str,
        service: str,
        action: str,
        user_id: int | None = None,
        payload: dict[str, Any] | None = None,
        duration_ms: int | None = None,
    ) -> TechLog:
        row = TechLog(
            trace_id=trace_id,
            service=service,
            action=action,
            user_id=user_id,
            payload=payload,
            duration_ms=duration_ms,
        )
        self.session.add(row)
        await self.session.flush()
        return row
