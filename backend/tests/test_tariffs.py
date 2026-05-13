"""Tariff endpoint tests."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_list_tariffs_after_seed(client, auth_headers, seed_db):  # noqa: ANN001
    r = await client.get("/api/bot/tariffs", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    codes = {t["code"] for t in body}
    # Conversion-pack 2026-05-13: Ultra removed, FREE expanded to 5d.
    assert {"free", "basic", "plus", "max"} <= codes
    assert "ultra" not in codes

    # Sorted by sort_order
    sort_orders = [t["sort_order"] for t in body]
    assert sort_orders == sorted(sort_orders)

    # FREE has no durations.
    free = next(t for t in body if t["code"] == "free")
    assert free["is_free_trial"] is True
    assert free["free_trial_days"] == 5
    assert free["durations"] == []
    # 2026-05-13: все 4 публичных тарифа выдают безлимит NorthLine'у.
    for code in ("free", "basic", "plus", "max"):
        tariff = next(t for t in body if t["code"] == code)
        assert tariff["is_unlimited_traffic"] is True, code

    # Paid tariffs have 4 durations sorted by days
    basic = next(t for t in body if t["code"] == "basic")
    days = [d["days"] for d in basic["durations"]]
    assert days == sorted(days)
    assert all(d["price_kopecks"] > 0 for d in basic["durations"])


@pytest.mark.asyncio
async def test_list_tariffs_requires_token(client, seed_db):  # noqa: ANN001
    r = await client.get("/api/bot/tariffs")
    assert r.status_code == 401
