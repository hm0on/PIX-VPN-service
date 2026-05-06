"""Periodically reconcile local subscription state with NorthLine.

Runs every 6 hours (offset to avoid colliding with the other hourly
crons). Just calls the backend endpoint that does the actual work — the
worker doesn't talk to NorthLine directly so credentials live in one
place.

See ``backend/app/services/subscription_reconcile_service.py`` for the
reconciliation policy. Test-mode keys (``nlsub_test_*``) are skipped on
the backend side.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.logging_setup import get_logger


async def reconcile_subscriptions_task(ctx: dict[str, Any]) -> dict[str, Any]:
    """ARQ cron entrypoint."""
    api_client: httpx.AsyncClient = ctx["api_client"]
    log = get_logger("worker.reconcile_subscriptions")

    try:
        resp = await api_client.post(
            "/api/bot/subscriptions/reconcile",
            params={"batch_size": 200},
            # Reconciling 200 subs against the provider can take a
            # while if the provider is slow — give the request more
            # headroom than the default 30s read timeout.
            timeout=httpx.Timeout(connect=5.0, read=180.0, write=10.0, pool=5.0),
        )
    except httpx.HTTPError as exc:
        log.warning("reconcile_request_failed", error=str(exc))
        return {"status": "error", "error": str(exc)}

    if resp.status_code >= 400:
        log.warning(
            "reconcile_backend_error",
            status=resp.status_code,
            body=resp.text[:500],
        )
        return {"status": "error", "http_status": resp.status_code}

    body = resp.json() if resp.content else {}
    log.info("reconcile_summary", **body)
    return {"status": "ok", **body}


__all__ = ["reconcile_subscriptions_task"]
