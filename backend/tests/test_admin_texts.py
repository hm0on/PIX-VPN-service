"""Stage 5 admin texts tests."""

from __future__ import annotations

import pytest
import pytest_asyncio

from app.db.models.text import Text as TextModel
from app.db.session import get_session_factory


@pytest_asyncio.fixture
async def admin_headers(client, seed_db, admin_initial_key):  # noqa: ANN001
    r = await client.post("/api/admin/auth/login", json={"key": admin_initial_key})
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def make_text(seed_db):  # noqa: ANN001
    async def _factory(key: str = "demo_key", value: str = "<b>demo</b>") -> int:
        factory = get_session_factory()
        async with factory() as session:
            row = TextModel(key=key, value_html=value, description="demo")
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row.id

    return _factory


@pytest.mark.asyncio
async def test_list_texts(client, admin_headers, make_text):  # noqa: ANN001
    await make_text("k1")
    await make_text("k2", "<i>hello</i>")
    r = await client.get("/api/admin/texts", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] >= 2
    keys = {t["key"] for t in body["items"]}
    assert {"k1", "k2"} <= keys


@pytest.mark.asyncio
async def test_patch_text(client, admin_headers, make_text):  # noqa: ANN001
    await make_text("k_edit", "<b>old</b>")
    r = await client.patch(
        "/api/admin/texts/k_edit",
        json={"value_html": "<b>new</b>", "description": "updated"},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["value_html"] == "<b>new</b>"
    assert r.json()["description"] == "updated"


@pytest.mark.asyncio
async def test_patch_missing_text_404(client, admin_headers):  # noqa: ANN001
    r = await client.patch(
        "/api/admin/texts/no_such_key",
        json={"value_html": "x"},
        headers=admin_headers,
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_requires_jwt(client, seed_db):  # noqa: ANN001
    r = await client.get("/api/admin/texts")
    assert r.status_code == 401
