"""Internal subscription maintenance endpoints (called by the worker)."""

from __future__ import annotations

from fastapi import APIRouter

from app.deps import DBSession, NorthLineClientDep
from app.services.subscription_reconcile_service import reconcile_subscriptions

router = APIRouter()


@router.post("/subscriptions/reconcile")
async def reconcile_endpoint(
    session: DBSession,
    northline: NorthLineClientDep,
    batch_size: int = 200,
) -> dict[str, int]:
    """Reconcile up to ``batch_size`` active subscriptions with NorthLine.

    Worker calls this on a slow cron (every 6h). Returns a small JSON
    summary so the worker can log it. See
    ``app.services.subscription_reconcile_service`` for the policy.
    """
    return dict(
        await reconcile_subscriptions(
            session, northline=northline, batch_size=batch_size
        )
    )


__all__ = ["router"]
