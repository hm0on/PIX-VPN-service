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
    async def _factory(
        key: str = "demo_key",
        value: str = "<b>demo</b>",
        kind: str = "message",
        icon_custom_emoji_id: str | None = None,
    ) -> int:
        factory = get_session_factory()
        async with factory() as session:
            row = TextModel(
                key=key,
                value_html=value,
                description="demo",
                kind=kind,
                icon_custom_emoji_id=icon_custom_emoji_id,
            )
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


# --- Phase 1: button-kind rows ------------------------------------------------


@pytest.mark.asyncio
async def test_button_patch_rejects_html(client, admin_headers, make_text):  # noqa: ANN001
    """For kind='button' rows, value_html must be plain text — Telegram
    does not accept HTML in InlineKeyboardButton.text."""
    await make_text("btn.demo", value="Каталог", kind="button")
    r = await client.patch(
        "/api/admin/texts/btn.demo",
        json={"value_html": "<b>Каталог</b>"},
        headers=admin_headers,
    )
    assert r.status_code == 422, r.text
    assert "plain text" in r.text.lower() or "html" in r.text.lower()


@pytest.mark.asyncio
async def test_button_patch_accepts_plain_label(client, admin_headers, make_text):  # noqa: ANN001
    await make_text("btn.demo2", value="Old", kind="button")
    r = await client.patch(
        "/api/admin/texts/btn.demo2",
        json={"value_html": "📚 Каталог книг"},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["value_html"] == "📚 Каталог книг"
    assert body["kind"] == "button"


@pytest.mark.asyncio
async def test_button_patch_accepts_icon_custom_emoji_id(
    client, admin_headers, make_text  # noqa: ANN001
):
    """Setting + clearing icon_custom_emoji_id round-trips correctly."""
    await make_text("btn.demo3", value="Профиль", kind="button")

    # Set the icon.
    r = await client.patch(
        "/api/admin/texts/btn.demo3",
        json={"icon_custom_emoji_id": "5407025283456398491"},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["icon_custom_emoji_id"] == "5407025283456398491"

    # Clear it.
    r = await client.patch(
        "/api/admin/texts/btn.demo3",
        json={"icon_custom_emoji_id": None},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["icon_custom_emoji_id"] is None


@pytest.mark.asyncio
async def test_button_patch_strips_whitespace_in_emoji_id(
    client, admin_headers, make_text  # noqa: ANN001
):
    await make_text("btn.demo4", value="X", kind="button")
    r = await client.patch(
        "/api/admin/texts/btn.demo4",
        json={"icon_custom_emoji_id": "  5407025283456398491  "},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["icon_custom_emoji_id"] == "5407025283456398491"


@pytest.mark.asyncio
async def test_message_patch_still_accepts_html(client, admin_headers, make_text):  # noqa: ANN001
    """Regression: HTML rejection must apply only to kind='button'."""
    await make_text("msg.demo", value="<b>old</b>", kind="message")
    r = await client.patch(
        "/api/admin/texts/msg.demo",
        json={"value_html": "<b>new</b><i>bold</i>"},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["value_html"] == "<b>new</b><i>bold</i>"


@pytest.mark.asyncio
async def test_list_returns_kind_field(client, admin_headers, make_text):  # noqa: ANN001
    """The list endpoint must surface the new kind discriminator."""
    await make_text("msg.x", value="hi", kind="message")
    await make_text("btn.y", value="Click", kind="button",
                    icon_custom_emoji_id="123")
    r = await client.get("/api/admin/texts", headers=admin_headers)
    assert r.status_code == 200, r.text
    by_key = {t["key"]: t for t in r.json()["items"]}
    assert by_key["msg.x"]["kind"] == "message"
    assert by_key["msg.x"]["icon_custom_emoji_id"] is None
    assert by_key["btn.y"]["kind"] == "button"
    assert by_key["btn.y"]["icon_custom_emoji_id"] == "123"
