"""One-shot: re-issue active FREE-trial keys with the new tariff config.

Background
----------
Migration 0014 shrunk the FREE tariff to *1 device, 0 GB LTE* (was 3 dev,
35 GB LTE). The change only affects keys issued **after** the deploy —
9 trials issued earlier today were still running the old (generous)
config. Ops asked us to re-cut them so everybody on FREE has the same
shape.

What this script does, per active FREE subscription
---------------------------------------------------
1. ``NorthLine.delete_key`` the old ``provider_subscription_id``. This is
   the irreversible "kill it now" endpoint; the user's V2RayTun
   immediately stops getting config and any leftover balance is refunded
   to the reseller account.
2. Flip the local row to ``status='deactivated'`` with a reason that
   marks it as a reissue (so the audit log doesn't look like ops
   manually nuked the user).
3. Create a brand-new ``Subscription`` row + ``NorthLine.create_key``
   call using the current ``Tariff(code='free')`` config — so the new
   key inherits ``devices`` and ``lte_gb_per_month`` from the row that
   migration 0014 already updated.
4. Enqueue an outbox row using the ``free_trial_reissued`` text
   template so the user gets the new ``key_url`` in chat.

The free-trial "already used" guard in
``FreeTrialService.activate_free_trial`` is **bypassed on purpose** —
this is a server-side reissue, not a user action.

Idempotency
-----------
Re-running the script is safe: only rows whose ``status='active'`` AND
whose tariff is the FREE one are touched. After step 2 each row is
``deactivated``, so a second run finds nothing to do. The newly-created
sub starts in ``status='pending'`` until the NorthLine call completes;
if NorthLine fails halfway through (network / provider error) we leave
the new row in ``status='failed'`` and skip the outbox so we don't
mislead the user. The next run will retry only the still-active old
trials, not the failed new ones (different ``status``).

Run
---
    docker compose -f infra/docker-compose.yml exec backend \\
        python -m scripts.reissue_free_trials
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.config import get_settings
from app.core.exceptions import NorthLineClientError, NorthLineUnavailableError
from app.db.models.outbox import OUTBOX_MSG_TEXT
from app.db.models.subscription import (
    SUB_STATUS_ACTIVE,
    SUB_STATUS_DEACTIVATED,
    SUB_STATUS_FAILED,
    SUB_STATUS_PENDING,
    Subscription,
)
from app.db.models.tariff import Tariff
from app.db.models.user import User
from app.db.session import get_session_factory
from app.repositories.outbox_repo import OutboxRepository
from app.repositories.subscription_repo import SubscriptionRepository
from app.services.northline_client import NorthLineClient


REISSUE_REASON = (
    "Auto-reissue after FREE tariff config change (1 device, 0 GB LTE)."
)


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


async def _build_northline() -> NorthLineClient:
    settings = get_settings()
    if not (settings.northline_api_url and settings.northline_bearer_token):
        raise RuntimeError(
            "NORTHLINE_API_URL / NORTHLINE_BEARER_TOKEN must be set in .env"
        )
    return NorthLineClient(
        base_url=settings.northline_api_url,
        bearer_token=settings.northline_bearer_token,
        provider_key=settings.northline_provider_key or "",
        test_mode=bool(settings.northline_test_mode),
    )


async def main() -> int:
    factory = get_session_factory()
    northline = await _build_northline()

    # 1. Snapshot of work to do. Done in its own session so the loop below
    #    doesn't hold a transaction open across every NorthLine call.
    async with factory() as session:
        rows = (
            await session.execute(
                select(Subscription)
                .join(Tariff, Tariff.id == Subscription.tariff_id)
                .where(Tariff.code == "free")
                .where(Subscription.status == SUB_STATUS_ACTIVE)
            )
        ).scalars().all()
        targets = [
            (
                sub.id,
                sub.user_id,
                sub.tariff_id,
                sub.provider_subscription_id,
            )
            for sub in rows
        ]

    if not targets:
        print("No active FREE subscriptions found — nothing to do.")
        return 0

    print(f"Found {len(targets)} active FREE subscription(s) to reissue.\n")

    ok = 0
    failed = 0
    for old_sub_id, user_id, tariff_id, provider_id in targets:
        print(f"[sub#{old_sub_id} user#{user_id}] starting reissue...")
        # Each row gets its own transaction so a half-applied step doesn't
        # leak into the next subscription's bookkeeping.
        try:
            await _reissue_one(
                factory=factory,
                northline=northline,
                old_sub_id=old_sub_id,
                user_id=user_id,
                tariff_id=tariff_id,
                old_provider_id=provider_id,
            )
            ok += 1
            print(f"[sub#{old_sub_id}] ✅ reissued")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"[sub#{old_sub_id}] ❌ failed: {exc!r}", file=sys.stderr)

    print(f"\nDone. ok={ok} failed={failed} total={len(targets)}")
    return 0 if failed == 0 else 1


async def _reissue_one(  # noqa: PLR0913
    *,
    factory,
    northline: NorthLineClient,
    old_sub_id: int,
    user_id: int,
    tariff_id: int,
    old_provider_id: str | None,
) -> None:
    # ----- Step 1: kill the old key on NorthLine -----
    # Test-mode subs (or rows that somehow never got a provider id) skip
    # the provider call; the local-side bookkeeping below still happens.
    if old_provider_id and not (
        old_provider_id.startswith("nlsub_test_")
        or old_provider_id.startswith("test_")
    ):
        try:
            await northline.delete_key(
                subscription_id=old_provider_id,
                idempotency_key=f"reissue-free-{old_sub_id}",
            )
        except NorthLineClientError as exc:
            # 404 / invalid_provider_key — provider has already lost the
            # row (e.g. someone deleted it manually). Carry on; the local
            # deactivation below is still the right move.
            err = (exc.error_code or "").lower()
            if err not in {"invalid_provider_key", "not_found"}:
                raise

    # ----- Step 2 + 3: local bookkeeping + new key -----
    async with factory() as session:
        # Refetch the row inside this session so the ORM state is fresh.
        old_sub = (
            await session.execute(
                select(Subscription).where(Subscription.id == old_sub_id)
            )
        ).scalar_one()
        tariff = (
            await session.execute(select(Tariff).where(Tariff.id == tariff_id))
        ).scalar_one()
        user = (
            await session.execute(select(User).where(User.id == user_id))
        ).scalar_one()

        now = _now()
        old_sub.status = SUB_STATUS_DEACTIVATED
        old_sub.deactivated_at = now
        old_sub.deactivation_reason = REISSUE_REASON
        await session.flush()

        # New subscription row with the post-migration config. We read
        # ``devices`` and ``lte_gb_per_month`` from the tariff row so the
        # values stay tied to the seed/admin source of truth.
        days = tariff.free_trial_days or 3
        devices = int(tariff.devices) or 1
        lte_gb = int(tariff.lte_gb_per_month) if tariff.lte_gb_per_month is not None else None
        unlimited_traffic = bool(getattr(tariff, "is_unlimited_traffic", False))

        subs_repo = SubscriptionRepository(session)
        new_sub = await subs_repo.create(
            user_id=user.id,
            tariff_id=tariff.id,
            tariff_duration_id=None,
            devices=devices,
            days=days,
            status=SUB_STATUS_PENDING,
            is_free_trial=True,
        )
        await session.commit()
        new_sub_id = new_sub.id

    # NorthLine call lives outside the DB transaction — same pattern as
    # ``BalanceService.purchase_with_balance`` to avoid holding locks
    # across a slow upstream call.
    idempotency_key = str(uuid.uuid4())
    try:
        key_resp = await northline.create_key(
            days=days,
            devices=devices,
            idempotency_key=idempotency_key,
            lte_gb=lte_gb,
            unlimited_traffic=True if unlimited_traffic else None,
            metadata={
                "user_tg_id": user.tg_id,
                "internal_subscription_id": str(new_sub_id),
                "free_trial": True,
                "reissue_of": str(old_sub_id),
            },
        )
    except (NorthLineUnavailableError, NorthLineClientError):
        async with factory() as session:
            failed_sub = (
                await session.execute(
                    select(Subscription).where(Subscription.id == new_sub_id)
                )
            ).scalar_one()
            failed_sub.status = SUB_STATUS_FAILED
            await session.commit()
        raise

    # ----- Step 4: activate the new row + outbox -----
    async with factory() as session:
        new_sub = (
            await session.execute(
                select(Subscription).where(Subscription.id == new_sub_id)
            )
        ).scalar_one()
        user = (
            await session.execute(select(User).where(User.id == user_id))
        ).scalar_one()

        now = _now()
        new_sub.status = SUB_STATUS_ACTIVE
        new_sub.provider_subscription_id = key_resp.subscription_id
        new_sub.key_url = key_resp.key
        new_sub.started_at = now
        # Ignore provider's ``expires_at`` for the same reason
        # FreeTrialService does — test-mode returns ``now``.
        new_sub.expires_at = now + timedelta(days=days)
        await session.flush()

        outbox = OutboxRepository(session)
        await outbox.enqueue(
            user_id=user.id,
            chat_id=user.tg_id,
            message_type=OUTBOX_MSG_TEXT,
            payload={
                "text_key": "free_trial_reissued",
                "format_kwargs": {"key_url": key_resp.key},
                "parse_mode": "HTML",
                "kind": "free_trial_reissued",
                "subscription_id": new_sub.id,
            },
        )
        await session.commit()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
