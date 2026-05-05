"""Tests for ``TextService.get_button`` (Stage 6 — editable button labels).

Covers the three ways an inline-button label can be resolved:

- **API hit**: backend returned a row with ``kind='button'`` — the cached
  label and ``icon_custom_emoji_id`` flow through unchanged.
- **API miss + button fallback**: backend hasn't returned the key (e.g. cold
  start before the bot's first refresh succeeded), but ``_BUTTON_FALLBACKS``
  mirrors the seeded labels so the UI still works.
- **Total miss**: unknown key — we return ``("???", None)`` and log
  ``texts.missing_key`` so it's loud in production.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.utils.texts import _BUTTON_FALLBACKS, TextService


def _make_service(api_payload: dict[str, dict[str, Any]] | None = None) -> TextService:
    """Build a TextService with a mocked BackendClient.get_all_texts."""
    api = AsyncMock()
    api.get_all_texts = AsyncMock(return_value=api_payload or {})
    return TextService(api=api, ttl_seconds=60)


@pytest.mark.asyncio
async def test_get_button_returns_label_and_icon_from_api():
    """Backend row with kind='button' → label + icon_custom_emoji_id."""
    svc = _make_service(
        {
            "btn.main_menu.catalog": {
                "value_html": "📚 Каталог книг",
                "kind": "button",
                "icon_custom_emoji_id": "5407025283456398491",
                "media_file_id": None,
                "media_kind": None,
            }
        }
    )

    label, icon = await svc.get_button("btn.main_menu.catalog")
    assert label == "📚 Каталог книг"
    assert icon == "5407025283456398491"


@pytest.mark.asyncio
async def test_get_button_handles_null_icon():
    """Buttons without a premium icon return None for the second tuple slot."""
    svc = _make_service(
        {
            "btn.profile.topup": {
                "value_html": "Пополнить",
                "kind": "button",
                "icon_custom_emoji_id": None,
            }
        }
    )

    label, icon = await svc.get_button("btn.profile.topup")
    assert label == "Пополнить"
    assert icon is None


@pytest.mark.asyncio
async def test_get_button_falls_back_to_hardcoded_dict():
    """When the backend payload is empty the seeded label still resolves —
    the hardcoded dict mirrors the alembic migration seeds so cold-start has
    a usable UI even before the first successful API refresh."""
    svc = _make_service({})  # backend returns nothing

    label, icon = await svc.get_button("btn.main_menu.catalog")
    assert label == _BUTTON_FALLBACKS["btn.main_menu.catalog"]
    assert label == "Каталог"
    # Fallback rows have no icon — operators can only set one through admin.
    assert icon is None


@pytest.mark.asyncio
async def test_get_button_unknown_key_returns_placeholder():
    """A key that's neither in the cache nor the fallback dict yields the
    loud ``???`` placeholder so the bug is visible without crashing."""
    svc = _make_service({})

    label, icon = await svc.get_button("btn.does.not.exist")
    assert label == "???"
    assert icon is None


@pytest.mark.asyncio
async def test_get_button_format_kwargs_render_into_label():
    """``str.format`` is applied to button labels too — useful for things
    like a counter ('Корзина ({count})') without re-coding the keyboard."""
    svc = _make_service(
        {
            "btn.cart.open": {
                "value_html": "Корзина ({count})",
                "kind": "button",
                "icon_custom_emoji_id": None,
            }
        }
    )

    label, icon = await svc.get_button("btn.cart.open", count=3)
    assert label == "Корзина (3)"
    assert icon is None


@pytest.mark.asyncio
async def test_get_button_api_overrides_fallback():
    """Once the backend confirms a label, it wins over the hardcoded dict —
    that's how operators see their admin-panel edits in the bot."""
    svc = _make_service(
        {
            "btn.main_menu.catalog": {
                "value_html": "🚀 New Catalog",
                "kind": "button",
                "icon_custom_emoji_id": "999",
            }
        }
    )

    label, icon = await svc.get_button("btn.main_menu.catalog")
    assert label == "🚀 New Catalog"
    assert icon == "999"


@pytest.mark.asyncio
async def test_get_button_fallbacks_cover_all_phase1_keys():
    """Sanity check: every seed key from the migration must have a fallback —
    otherwise a Backend outage during cold start would crash the menu."""
    expected_keys = {
        "btn.main_menu.catalog",
        "btn.main_menu.profile",
        "btn.main_menu.support",
        "btn.main_menu.promo",
        "btn.main_menu.idea",
        "btn.main_menu.about",
        "btn.common.back",
        "btn.common.subscribe",
        "btn.common.subscribed",
        "btn.profile.topup",
        "btn.profile.referral",
        "btn.subscription.howto",
        "btn.subscription.extend",
        "btn.payment.sbp",
        "btn.payment.cryptobot",
        "btn.payment.balance",
        "btn.payment.balance_locked",
        "btn.payment.pay",
        "btn.ticket.create_support",
        "btn.ticket.close_yes",
        "btn.ticket.close_no",
    }
    missing = expected_keys - _BUTTON_FALLBACKS.keys()
    assert not missing, f"Missing fallbacks for: {sorted(missing)}"


@pytest.mark.asyncio
async def test_get_returns_button_label_for_button_keys_too():
    """``get`` is the legacy code-path — it should still return *something*
    sensible for a button key (just the label, no icon). Callers that need
    the icon use ``get_button``."""
    svc = _make_service(
        {
            "btn.profile.topup": {
                "value_html": "💰 Топ-ап",
                "kind": "button",
                "icon_custom_emoji_id": "42",
            }
        }
    )

    text = await svc.get("btn.profile.topup")
    assert text == "💰 Топ-ап"
