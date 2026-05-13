"""Per-subscription branding helpers for NorthLine.

The reseller account has a default branding (``PIX VPN``) installed via
``scripts/apply_branding.py``. We override ``service_name`` at the
sub-level so the VPN client displays which tariff a user is on:

- FREE-trial   → ``PIX VPN · TRIAL``
- Basic        → ``PIX VPN · BASIC``
- Plus         → ``PIX VPN · PLUS``
- Max          → ``PIX VPN · MAX``
- любой другой → ``PIX VPN · {CODE.upper()}``

Per docs (POST /keys): передаём через тело ``"branding": {...}`` при
создании ключа. ``custom_domain``/``service_description``/``support_url``
наследуются из reseller-defaults — мы их в override не дублируем, чтобы
случайная правка дефолтов отражалась и в новых ключах.
"""

from __future__ import annotations

from typing import Any

# Базовое имя сервиса — должно совпадать с reseller-default
# из ``scripts/apply_branding.py``. Меняется через админку
# (PUT /admin/northline/branding) — тогда оба места обновятся.
BASE_SERVICE_NAME = "PIX VPN"


def _tariff_label(*, code: str | None, is_free_trial: bool) -> str:
    """Resolve the suffix shown after ``PIX VPN · ``.

    FREE-trial всегда «TRIAL» (а не «FREE») — это маркетинговый сигнал.
    Для остальных тарифов берём ``code.upper()`` (basic→BASIC и т.д.).
    """
    if is_free_trial:
        return "TRIAL"
    if not code:
        return ""
    return str(code).strip().upper()


def build_subscription_branding(
    *,
    tariff_code: str | None,
    is_free_trial: bool = False,
) -> dict[str, Any] | None:
    """Build the per-key ``branding`` payload for ``POST /keys``.

    Returns ``None`` if no meaningful label can be derived — callers
    should skip the ``branding`` field entirely in that case so the
    provider falls back to the reseller-default ``service_name``.
    """
    label = _tariff_label(code=tariff_code, is_free_trial=is_free_trial)
    if not label:
        return None
    return {"service_name": f"{BASE_SERVICE_NAME} · {label}"}
