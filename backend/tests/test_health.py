"""Health endpoint tests."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_public_health(client):  # noqa: ANN001
    r = await client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in {"ok", "degraded"}
    assert body["db"] in {"ok", "fail"}


@pytest.mark.asyncio
async def test_bot_health_requires_token(client):  # noqa: ANN001
    r = await client.get("/api/bot/health")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_bot_health_with_token(client, auth_headers):  # noqa: ANN001
    r = await client.get("/api/bot/health", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["ok"] is True
