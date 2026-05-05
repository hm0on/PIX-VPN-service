"""Text endpoint tests."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_get_text_after_seed(client, auth_headers, seed_db):  # noqa: ANN001
    r = await client.get("/api/bot/texts/main_menu", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["key"] == "main_menu"
    assert "<b>" in body["value_html"]


@pytest.mark.asyncio
async def test_list_texts_after_seed(client, auth_headers, seed_db):  # noqa: ANN001
    r = await client.get("/api/bot/texts", headers=auth_headers)
    assert r.status_code == 200
    keys = {t["key"] for t in r.json()}
    assert {"main_menu", "section_in_development", "channel_subscription_required"} <= keys


@pytest.mark.asyncio
async def test_get_text_missing(client, auth_headers, seed_db):  # noqa: ANN001
    r = await client.get("/api/bot/texts/no_such_key", headers=auth_headers)
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "text_not_found"
