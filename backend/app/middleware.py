"""HTTP middleware: trace_id propagation + tech-log of every request."""

from __future__ import annotations

import os
import time
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.core.logging import get_logger, new_trace_id, set_trace_id, tech_log
from app.db.session import get_session_factory

_TECH_LOG_PERSIST_ENABLED = os.environ.get("TECH_LOG_PERSIST", "1").lower() in {"1", "true", "yes"}

logger = get_logger("http")


class TraceIDMiddleware(BaseHTTPMiddleware):
    """Read X-Trace-ID or generate a new UUIDv4. Make it available in ContextVar."""

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        incoming = request.headers.get("X-Trace-ID")
        trace_id = incoming.strip() if incoming else new_trace_id()
        set_trace_id(trace_id)
        request.state.trace_id = trace_id

        response = await call_next(request)
        response.headers["X-Trace-ID"] = trace_id
        return response


# Paths excluded from tech-log persistence (avoid noise + recursive logging on /health).
_EXCLUDED_TECH_LOG_PATHS = {
    "/health",
    "/api/bot/health",
    "/api/admin/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/favicon.ico",
}


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Persist a tech-log entry per HTTP request and structured stdout log."""

    def __init__(self, app: ASGIApp, *, service: str = "backend") -> None:
        super().__init__(app)
        self.service = service

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        start = time.perf_counter()
        path = request.url.path
        method = request.method
        status_code: int = 500

        try:
            response: Response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            duration_ms = int((time.perf_counter() - start) * 1000)
            trace_id = getattr(request.state, "trace_id", None)

            logger.info(
                "http_request",
                method=method,
                path=path,
                status_code=status_code,
                duration_ms=duration_ms,
                trace_id=trace_id,
            )

            # Persist a tech_log row (best-effort, never break request flow).
            if _TECH_LOG_PERSIST_ENABLED and path not in _EXCLUDED_TECH_LOG_PATHS:
                try:
                    factory = get_session_factory()
                    async with factory() as session:
                        await tech_log(
                            session,
                            service=self.service,
                            action=f"http:{method}:{path}",
                            payload={
                                "status_code": status_code,
                                "method": method,
                                "path": path,
                                "query": str(request.url.query) or None,
                            },
                            duration_ms=duration_ms,
                            trace_id=trace_id,
                        )
                        await session.commit()
                except Exception as e:  # noqa: BLE001
                    logger.warning("tech_log_persist_failed", error=str(e))
