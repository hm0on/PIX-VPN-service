"""Stage 5 admin logs tests."""

from __future__ import annotations

import pytest
import pytest_asyncio

from app.db.models.log import Log, TechLog
from app.db.session import get_session_factory


@pytest_asyncio.fixture
async def admin_headers(client, seed_db, admin_initial_key):  # noqa: ANN001
    r = await client.post("/api/admin/auth/login", json={"key": admin_initial_key})
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def make_logs(seed_db):  # noqa: ANN001
    async def _factory() -> tuple[list[int], list[int]]:
        factory = get_session_factory()
        async with factory() as session:
            log_ids: list[int] = []
            for i in range(3):
                row = Log(
                    level=i % 3,
                    event="test_event",
                    module="bot",
                    message=f"msg {i}",
                    context={"i": i},
                )
                session.add(row)
                await session.flush()
                log_ids.append(row.id)
            tech_ids: list[int] = []
            for i in range(2):
                t = TechLog(
                    trace_id="abc-123",
                    service="backend",
                    action="do_thing",
                    payload={"i": i},
                )
                session.add(t)
                await session.flush()
                tech_ids.append(t.id)
            await session.commit()
            return log_ids, tech_ids

    return _factory


@pytest.mark.asyncio
async def test_list_events(client, admin_headers, make_logs):  # noqa: ANN001
    await make_logs()
    r = await client.get("/api/admin/logs/events", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body["items"], list)
    assert len(body["items"]) >= 3


@pytest.mark.asyncio
async def test_list_events_with_filters(client, admin_headers, make_logs):  # noqa: ANN001
    await make_logs()
    r = await client.get(
        "/api/admin/logs/events?level=warning&module=bot&q=msg",
        headers=admin_headers,
    )
    assert r.status_code == 200
    items = r.json()["items"]
    assert all(it["level"] == 1 for it in items)


@pytest.mark.asyncio
async def test_list_events_cursor(client, admin_headers, make_logs):  # noqa: ANN001
    await make_logs()
    r = await client.get(
        "/api/admin/logs/events?limit=1", headers=admin_headers
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 1
    assert body["next_before_id"] is not None


@pytest.mark.asyncio
async def test_list_tech_logs(client, admin_headers, make_logs):  # noqa: ANN001
    await make_logs()
    r = await client.get("/api/admin/logs/tech", headers=admin_headers)
    assert r.status_code == 200
    assert len(r.json()["items"]) >= 2


@pytest.mark.asyncio
async def test_get_trace_chain(client, admin_headers, make_logs):  # noqa: ANN001
    await make_logs()
    r = await client.get(
        "/api/admin/logs/tech/trace/abc-123",
        headers=admin_headers,
    )
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 2
    assert all(it["trace_id"] == "abc-123" for it in items)


@pytest.mark.asyncio
async def test_get_trace_unknown(client, admin_headers):  # noqa: ANN001
    r = await client.get(
        "/api/admin/logs/tech/trace/nope", headers=admin_headers
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_requires_jwt(client, seed_db):  # noqa: ANN001
    r = await client.get("/api/admin/logs/events")
    assert r.status_code == 401
