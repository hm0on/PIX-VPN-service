"""Worker task modules.

Stage 2 tasks:
    - outbox_dispatcher       — drains outbox → Telegram
    - expire_pending_payments — marks stale `pending` payments as expired
    - cleanup_idempotency     — TTL-based idempotency-keys cleanup

Stage 3 tasks:
    - notify_expiring_subscriptions — expiry-3d reminder
    - mark_expired_subscriptions    — flip active→expired
    - notify_expired_subscriptions  — "your sub expired" notice
"""

from app.tasks.broadcasts import (
    cleanup_logs as cleanup_logs_task,
)
from app.tasks.broadcasts import (
    pick_scheduled_broadcasts as pick_scheduled_broadcasts_task,
)
from app.tasks.broadcasts import (
    run_broadcast as run_broadcast_task,
)
from app.tasks.cleanup_idempotency import cleanup_idempotency_keys_task
from app.tasks.expire_payments import expire_pending_payments_task
from app.tasks.mark_expired import mark_expired_subscriptions_task
from app.tasks.notify_expired import notify_expired_subscriptions_task
from app.tasks.notify_expiring import notify_expiring_subscriptions_task
from app.tasks.notify_trial_expiring import notify_trial_expiring_subscriptions_task
from app.tasks.outbox_dispatcher import outbox_dispatcher_task
from app.tasks.reconcile_subscriptions import reconcile_subscriptions_task

__all__ = [
    "cleanup_idempotency_keys_task",
    "cleanup_logs_task",
    "expire_pending_payments_task",
    "mark_expired_subscriptions_task",
    "notify_expired_subscriptions_task",
    "notify_expiring_subscriptions_task",
    "notify_trial_expiring_subscriptions_task",
    "outbox_dispatcher_task",
    "pick_scheduled_broadcasts_task",
    "reconcile_subscriptions_task",
    "run_broadcast_task",
]
