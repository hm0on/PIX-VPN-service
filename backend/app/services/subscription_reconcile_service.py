"""Periodic reconciliation of local subscriptions vs. NorthLine state.

Why this exists
---------------
We compute ``expires_at`` locally at issue time (``now + days``) instead
of trusting ``KeyResponse.expires_at`` from the provider, because the
NorthLine **test-mode** endpoint returns ``expires_at == now`` for fake
keys — which would mark the subscription as already expired.

That decision is correct for *issuing*, but it leaves a small risk in
production: if the provider mutates the key out-of-band (admin manually
shortens it, traffic quota auto-deactivation, etc.) we'd never know.
This service runs on a slow cron (every 6h) and pulls
``GET /keys/{id}`` for each active subscription, then:

* If provider's ``status != active`` → flip our row to ``expired`` /
  ``deactivated`` to match. The follow-up ``notify_expired`` cron will
  message the user via the existing pipeline.
* If provider's ``expires_at`` is **later** than ours by more than 1h →
  pull it forward (provider extended the key e.g. via admin panel).
* If provider's ``expires_at`` is **earlier** than ours by more than 1h
  → log a ``WARNING`` business event and DO NOT shorten locally. We err
  on the side of letting the user keep what they paid for; ops can
  investigate manually.

Test-mode keys (``provider_subscription_id`` starts with ``nlsub_test_``
or ``test_``, or the API returns 404 / ``invalid_provider_key``) are
skipped entirely — the provider doesn't really track them, comparing
expiry would always trigger a false alarm.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NorthLineClientError, NorthLineUnavailableError
from app.core.logging import LEVEL_INFO, LEVEL_WARNING, business_log, get_logger
from app.db.models.subscription import (
    SUB_STATUS_ACTIVE,
    SUB_STATUS_DEACTIVATED,
    SUB_STATUS_EXPIRED,
    Subscription,
)

if TYPE_CHECKING:
    from app.services.northline_client import NorthLineClient

log = get_logger("subscription_reconcile")

# How far provider/local expires_at can drift before we react. One hour
# absorbs typical clock skew + the latency between issuing the key and
# the provider materializing it on its side.
DRIFT_THRESHOLD = timedelta(hours=1)


def _is_test_subscription_id(sub_id: str | None) -> bool:
    """Heuristic: subscription IDs the provider only "knows" in test mode.

    Both prefixes have been observed: ``nlsub_test_*`` (issued by our
    backend in test mode) and bare ``test_*`` (older fixtures).
    """
    if not sub_id:
        return True
    return sub_id.startswith("nlsub_test_") or sub_id.startswith("test_")


class ReconcileResult(dict[str, int]):
    """Tiny structured result so the caller can log a one-liner.

    Keys:
        ``checked``       — how many active subs we tried to reconcile
        ``skipped_test``  — test-mode rows we deliberately ignored
        ``flipped``       — rows whose status moved active→expired/deactivated
        ``extended``      — rows whose expires_at was pulled forward
        ``shrink_warned`` — rows where provider had an earlier expiry
        ``api_errors``    — rows we couldn't check (network / 5xx / etc.)
    """


async def reconcile_subscriptions(
    session: AsyncSession,
    *,
    northline: NorthLineClient,
    batch_size: int = 200,
) -> ReconcileResult:
    """Reconcile the next ``batch_size`` active subscriptions.

    Single-process: we don't claim rows with a lock — collisions with a
    parallel worker are harmless because every UPDATE is idempotent and
    based on absolute values, not deltas.
    """
    result = ReconcileResult(
        checked=0,
        skipped_test=0,
        flipped=0,
        extended=0,
        shrink_warned=0,
        api_errors=0,
    )

    rows = (
        await session.execute(
            select(Subscription)
            .where(Subscription.status == SUB_STATUS_ACTIVE)
            .where(Subscription.provider_subscription_id.is_not(None))
            .order_by(Subscription.updated_at.asc())
            .limit(batch_size)
        )
    ).scalars().all()

    if not rows:
        log.debug("reconcile_no_active_subs")
        return result

    now = datetime.now(tz=timezone.utc)

    for sub in rows:
        provider_id = sub.provider_subscription_id
        if _is_test_subscription_id(provider_id):
            result["skipped_test"] += 1
            continue

        result["checked"] += 1

        try:
            info = await northline.get_key(subscription_id=str(provider_id))
        except NorthLineClientError as exc:
            # Provider says the key is unknown. In *test* mode this is
            # routine; in prod it means the row is genuinely gone — flip
            # to deactivated so the user/admin sees the truth.
            if (exc.error_code or "").lower() in {
                "invalid_provider_key",
                "key_not_found",
                "subscription_not_found",
                "not_found",
            }:
                sub.status = SUB_STATUS_DEACTIVATED
                sub.deactivated_at = now
                sub.deactivation_reason = (
                    f"Reconcile: provider returned {exc.error_code}"
                )
                result["flipped"] += 1
                await business_log(
                    session,
                    level=LEVEL_WARNING,
                    event="reconcile_provider_unknown_key",
                    user_id=sub.user_id,
                    message=(
                        f"Subscription {sub.id} unknown to NorthLine "
                        f"({exc.error_code}); marked deactivated."
                    ),
                    context={
                        "subscription_id": sub.id,
                        "provider_subscription_id": provider_id,
                        "provider_error_code": exc.error_code,
                    },
                )
                continue
            log.warning(
                "reconcile_provider_client_error",
                subscription_id=sub.id,
                error_code=exc.error_code,
            )
            result["api_errors"] += 1
            continue
        except NorthLineUnavailableError as exc:
            # Transient — leave the row alone, next run will retry.
            log.warning(
                "reconcile_provider_unavailable",
                subscription_id=sub.id,
                error=str(exc),
            )
            result["api_errors"] += 1
            continue

        # ----- Status drift -----
        provider_status = (info.status or "").lower()
        if provider_status and provider_status != "active":
            # Map provider status onto our enum. We treat anything
            # non-active as "expired" unless the provider explicitly
            # says it was deactivated/disabled.
            new_status = (
                SUB_STATUS_DEACTIVATED
                if provider_status in {"deactivated", "disabled", "cancelled"}
                else SUB_STATUS_EXPIRED
            )
            sub.status = new_status
            if new_status == SUB_STATUS_DEACTIVATED:
                sub.deactivated_at = now
                sub.deactivation_reason = (
                    f"Reconcile: provider status={provider_status}"
                )
            result["flipped"] += 1
            await business_log(
                session,
                level=LEVEL_INFO,
                event="reconcile_status_drift",
                user_id=sub.user_id,
                message=(
                    f"Subscription {sub.id} status drift: "
                    f"local=active provider={provider_status} "
                    f"→ {new_status}"
                ),
                context={
                    "subscription_id": sub.id,
                    "provider_subscription_id": provider_id,
                    "provider_status": provider_status,
                    "new_local_status": new_status,
                },
            )
            continue

        # ----- expires_at drift -----
        provider_exp = info.expires_at
        local_exp = sub.expires_at
        if provider_exp is None or local_exp is None:
            continue

        delta = provider_exp - local_exp
        if delta > DRIFT_THRESHOLD:
            # Provider gave the user *more* time — pull it in.
            old = local_exp.isoformat()
            sub.expires_at = provider_exp
            result["extended"] += 1
            await business_log(
                session,
                level=LEVEL_INFO,
                event="reconcile_expires_extended",
                user_id=sub.user_id,
                message=(
                    f"Subscription {sub.id} expires_at pulled forward: "
                    f"{old} → {provider_exp.isoformat()}"
                ),
                context={
                    "subscription_id": sub.id,
                    "provider_subscription_id": provider_id,
                    "old_expires_at": old,
                    "new_expires_at": provider_exp.isoformat(),
                    "delta_seconds": int(delta.total_seconds()),
                },
            )
        elif -delta > DRIFT_THRESHOLD:
            # Provider has an *earlier* expiry. We don't shorten — that
            # could destroy paid time. Surface as a warning for ops.
            result["shrink_warned"] += 1
            await business_log(
                session,
                level=LEVEL_WARNING,
                event="reconcile_expires_shrink_warning",
                user_id=sub.user_id,
                message=(
                    f"Subscription {sub.id} provider expires_at is earlier "
                    f"than local; not shortened automatically."
                ),
                context={
                    "subscription_id": sub.id,
                    "provider_subscription_id": provider_id,
                    "local_expires_at": local_exp.isoformat(),
                    "provider_expires_at": provider_exp.isoformat(),
                    "delta_seconds": int(delta.total_seconds()),
                },
            )

    await session.commit()

    log.info(
        "reconcile_done",
        checked=result["checked"],
        skipped_test=result["skipped_test"],
        flipped=result["flipped"],
        extended=result["extended"],
        shrink_warned=result["shrink_warned"],
        api_errors=result["api_errors"],
    )
    return result


__all__ = ["reconcile_subscriptions", "ReconcileResult"]
