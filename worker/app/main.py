"""ARQ entrypoint — `arq app.main.WorkerSettings`.

Stage 2 deliverable: outbox dispatcher + maintenance cron jobs.
On startup we now also boot a shared :class:`TelegramClient` so the
outbox dispatcher can talk to Telegram directly (no dependency on the
bot process being up).
"""

from __future__ import annotations

from typing import Any, ClassVar, cast

from arq import cron
from arq.connections import RedisSettings

from app.api_client import create_api_client
from app.config import Settings, get_settings
from app.db import create_engine, make_session_factory
from app.logging_setup import configure_logging, get_logger
from app.tasks import (
    cleanup_idempotency_keys_task,
    cleanup_logs_task,
    expire_pending_payments_task,
    mark_expired_subscriptions_task,
    notify_expired_subscriptions_task,
    notify_expiring_subscriptions_task,
    notify_trial_expiring_subscriptions_task,
    outbox_dispatcher_task,
    pick_scheduled_broadcasts_task,
    reconcile_subscriptions_task,
    run_broadcast_task,
)
from app.telegram_client import TelegramClient


# --------------------------------------------------------------------------- #
# Build redis settings from env once at import time. ARQ takes a RedisSettings
# instance directly on the WorkerSettings class.
# --------------------------------------------------------------------------- #
def _build_redis_settings(settings: Settings) -> RedisSettings:
    password = (
        settings.redis_password.get_secret_value() if settings.redis_password else None
    )
    return RedisSettings(
        host=settings.redis_host,
        port=settings.redis_port,
        password=password or None,
        database=settings.redis_database,
        # connection retries — the worker container may start a beat before
        # Redis is fully ready, even with docker-compose healthchecks.
        conn_retries=10,
        conn_retry_delay=2,
        conn_timeout=5,
    )


# --------------------------------------------------------------------------- #
# Lifecycle hooks
# --------------------------------------------------------------------------- #
async def on_startup(ctx: dict[str, Any]) -> None:
    """Initialize shared resources and store them in the ARQ context."""
    settings = get_settings()
    configure_logging(settings.log_level)
    log = get_logger("worker.startup")

    engine = create_engine(settings)
    session_factory = make_session_factory(engine)
    api_client = create_api_client(settings)
    telegram_client = TelegramClient(token=settings.bot_token.get_secret_value())

    ctx["settings"] = settings
    ctx["db_engine"] = engine
    ctx["db_session_factory"] = session_factory
    ctx["api_client"] = api_client
    ctx["telegram_client"] = telegram_client

    log.info(
        "Worker started",
        env=settings.env,
        queue=settings.arq_queue_name,
        max_jobs=settings.arq_max_jobs,
        backend_api_url=settings.backend_api_url,
        outbox_batch_size=settings.outbox_batch_size,
        outbox_concurrency=settings.outbox_concurrency,
    )


async def on_shutdown(ctx: dict[str, Any]) -> None:
    """Cleanly close shared resources."""
    log = get_logger("worker.shutdown")

    telegram_client = ctx.get("telegram_client")
    if telegram_client is not None:
        await telegram_client.aclose()

    api_client = ctx.get("api_client")
    if api_client is not None:
        await api_client.aclose()

    engine = ctx.get("db_engine")
    if engine is not None:
        await engine.dispose()

    log.info("Worker stopped, resources released")


# --------------------------------------------------------------------------- #
# WorkerSettings — read by ARQ via `arq app.main.WorkerSettings`.
# --------------------------------------------------------------------------- #
_settings = get_settings()
# Configure logging at import time so even pre-startup ARQ messages are JSON.
configure_logging(_settings.log_level)


# Cron schedules:
#   Stage 2:
#     - outbox dispatcher: every 5 seconds
#     - expire pending payments: every 5 minutes
#     - cleanup idempotency keys: hourly (offset by 17 minutes to spread load)
#   Stage 3 (all hourly, offsets chosen to spread load):
#     - notify_expiring_subscriptions: minute 23
#     - mark_expired_subscriptions:    minute 43
#     - notify_expired_subscriptions:  minute 53 (10 min after mark)
_OUTBOX_SECONDS: set[int] = set(range(0, 60, 5))
_EXPIRE_MINUTES: set[int] = set(range(0, 60, 5))
_CLEANUP_HOURS: set[int] = set(range(24))
_HOURLY_HOURS: set[int] = set(range(24))
# Reconcile subs vs. NorthLine every 6h at minute :11 (offset chosen to
# avoid the existing :17/:23/:33/:37/:43/:53 cron slots).
_RECONCILE_HOURS: set[int] = {1, 7, 13, 19}


class WorkerSettings:
    """ARQ worker configuration."""

    redis_settings: RedisSettings = _build_redis_settings(_settings)

    # On-demand jobs (Stage 5).
    functions: ClassVar[list[Any]] = [run_broadcast_task]

    cron_jobs: ClassVar[list[Any]] = [
        cron(
            outbox_dispatcher_task,
            name="outbox_dispatcher",
            second=_OUTBOX_SECONDS,
            run_at_startup=True,
            unique=True,
        ),
        cron(
            expire_pending_payments_task,
            name="expire_pending_payments",
            minute=_EXPIRE_MINUTES,
            unique=True,
        ),
        cron(
            cleanup_idempotency_keys_task,
            name="cleanup_idempotency_keys",
            hour=_CLEANUP_HOURS,
            minute={17},
            unique=True,
        ),
        cron(
            notify_expiring_subscriptions_task,
            name="notify_expiring_subscriptions",
            hour=_HOURLY_HOURS,
            minute={23},
            unique=True,
        ),
        cron(
            mark_expired_subscriptions_task,
            name="mark_expired_subscriptions",
            hour=_HOURLY_HOURS,
            minute={43},
            unique=True,
        ),
        cron(
            notify_expired_subscriptions_task,
            name="notify_expired_subscriptions",
            hour=_HOURLY_HOURS,
            minute={53},
            unique=True,
        ),
        # Conversion-pack 2026-05-13: -24h reminder for FREE trials.
        # Minute :37 free of other hourly slots (cleanup_logs is at
        # hour=3 only, so co-existence at 3:37 is fine — they're
        # separate named jobs).
        cron(
            notify_trial_expiring_subscriptions_task,
            name="notify_trial_expiring_subscriptions",
            hour=_HOURLY_HOURS,
            minute={37},
            unique=True,
        ),
        # Stage 5
        cron(
            pick_scheduled_broadcasts_task,
            name="pick_scheduled_broadcasts",
            minute=set(range(60)),
            second={33},
            unique=True,
        ),
        cron(
            cleanup_logs_task,
            name="cleanup_logs",
            hour={3},
            minute={37},
            unique=True,
        ),
        cron(
            reconcile_subscriptions_task,
            name="reconcile_subscriptions",
            hour=_RECONCILE_HOURS,
            minute={11},
            unique=True,
        ),
    ]

    on_startup = staticmethod(on_startup)
    on_shutdown = staticmethod(on_shutdown)

    queue_name: str = _settings.arq_queue_name
    max_jobs: int = _settings.arq_max_jobs
    job_timeout: int = _settings.arq_job_timeout_seconds
    keep_result: int = _settings.arq_keep_result_seconds

    health_check_interval: int = 60


# Help type-checkers — RedisSettings is a Pydantic model.
_ = cast("RedisSettings", WorkerSettings.redis_settings)
