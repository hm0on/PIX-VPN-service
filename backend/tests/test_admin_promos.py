"""Stage 5 admin promos tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def admin_headers(client, seed_db, admin_initial_key):  # noqa: ANN001
    r = await client.post("/api/admin/auth/login", json={"key": admin_initial_key})
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_create_and_list_promo(client, admin_headers):  # noqa: ANN001
    r = await client.post(
        "/api/admin/promos",
        json={"type": "balance", "value": 100, "max_per_user": 1},
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    auto_code = r.json()["code"]
    assert len(auto_code) >= 6

    r_list = await client.get("/api/admin/promos", headers=admin_headers)
    assert r_list.status_code == 200
    body = r_list.json()
    assert body["total"] >= 1
    assert any(p["id"] == pid for p in body["items"])

    # Filter by code substring
    r_search = await client.get(
        f"/api/admin/promos?code={auto_code[:3]}",
        headers=admin_headers,
    )
    assert r_search.status_code == 200


@pytest.mark.asyncio
async def test_create_with_explicit_code_and_window(client, admin_headers):  # noqa: ANN001
    valid_from = datetime.now(timezone.utc).replace(microsecond=0)
    valid_until = valid_from + timedelta(days=7)
    r = await client.post(
        "/api/admin/promos",
        json={
            "code": "summer24",
            "type": "discount_percent",
            "value": 25,
            "valid_from": valid_from.isoformat(),
            "valid_until": valid_until.isoformat(),
            "description": "Summer sale",
        },
        headers=admin_headers,
    )
    assert r.status_code == 201
    assert r.json()["code"] == "SUMMER24"


@pytest.mark.asyncio
async def test_invalid_window_rejected(client, admin_headers):  # noqa: ANN001
    now = datetime.now(timezone.utc).replace(microsecond=0)
    r = await client.post(
        "/api/admin/promos",
        json={
            "type": "balance",
            "value": 100,
            "valid_from": now.isoformat(),
            "valid_until": (now - timedelta(days=1)).isoformat(),
        },
        headers=admin_headers,
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_patch_only_allowed_fields(client, admin_headers):  # noqa: ANN001
    r = await client.post(
        "/api/admin/promos",
        json={"type": "balance", "value": 100},
        headers=admin_headers,
    )
    pid = r.json()["id"]

    # value and code are not editable — extra=forbid → 422
    rp_bad = await client.patch(
        f"/api/admin/promos/{pid}",
        json={"value": 200},
        headers=admin_headers,
    )
    assert rp_bad.status_code == 422

    rp = await client.patch(
        f"/api/admin/promos/{pid}",
        json={"is_active": False, "max_per_user": 5},
        headers=admin_headers,
    )
    assert rp.status_code == 200
    assert rp.json()["is_active"] is False
    assert rp.json()["max_per_user"] == 5


@pytest.mark.asyncio
async def test_activations_endpoint(client, admin_headers):  # noqa: ANN001
    r = await client.post(
        "/api/admin/promos",
        json={"type": "balance", "value": 100},
        headers=admin_headers,
    )
    pid = r.json()["id"]
    ra = await client.get(
        f"/api/admin/promos/{pid}/activations",
        headers=admin_headers,
    )
    assert ra.status_code == 200
    assert ra.json() == []


@pytest.mark.asyncio
async def test_requires_jwt(client, seed_db):  # noqa: ANN001
    r = await client.get("/api/admin/promos")
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# valid_until date-only -> end-of-day-Moscow normalization
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_promo_with_date_only_valid_until_snaps_to_end_of_day(  # noqa: ANN001
    client, admin_headers
):
    """The admin UI sends ``valid_until`` as ``YYYY-MM-DD``. We must
    interpret that as "valid through the end of that day in app TZ"
    (Europe/Moscow), not as midnight UTC — otherwise admins set "until
    May 9" and the promo silently rolls over hours later, on the wrong
    side of when they thought it should die. This was the HMOONCHIK
    "promo kept working past its date" bug.
    """
    r = await client.post(
        "/api/admin/promos",
        json={
            "type": "balance",
            "value": 500,
            "max_per_user": 1,
            "valid_until": "2030-05-09",
        },
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    # ISO-8601 string on the wire; Pydantic emits with tzinfo when present.
    parsed = datetime.fromisoformat(body["valid_until"])
    # The instant must land at end-of-day May 9 Moscow:
    # 23:59:59.999999 +03:00 == 20:59:59.999999 UTC.
    assert parsed.tzinfo is not None
    in_utc = parsed.astimezone(timezone.utc)
    assert in_utc.year == 2030 and in_utc.month == 5 and in_utc.day == 9
    assert in_utc.hour == 20 and in_utc.minute == 59 and in_utc.second == 59


@pytest.mark.asyncio
async def test_patch_promo_with_date_only_valid_until_snaps_to_end_of_day(  # noqa: ANN001
    client, admin_headers
):
    """Same end-of-day-Moscow rule must apply to PATCH so admins can fix
    promos like HMOONCHIK that were created before the snap-to-EOD fix.
    """
    rc = await client.post(
        "/api/admin/promos",
        json={"type": "balance", "value": 500, "max_per_user": 1},
        headers=admin_headers,
    )
    assert rc.status_code == 201, rc.text
    pid = rc.json()["id"]

    rp = await client.patch(
        f"/api/admin/promos/{pid}",
        json={"valid_until": "2030-05-09"},
        headers=admin_headers,
    )
    assert rp.status_code == 200, rp.text
    parsed = datetime.fromisoformat(rp.json()["valid_until"])
    in_utc = parsed.astimezone(timezone.utc)
    assert in_utc.year == 2030 and in_utc.month == 5 and in_utc.day == 9
    assert in_utc.hour == 20 and in_utc.minute == 59 and in_utc.second == 59


def test_coerce_validity_window_helpers():
    """Direct unit tests for the helper, independent of HTTP plumbing."""
    from app.schemas.admin_panel.promo import _coerce_validity_window

    # None passes through.
    assert _coerce_validity_window(None, end_of_day=False) is None
    assert _coerce_validity_window(None, end_of_day=True) is None

    # tz-aware datetimes are converted to UTC and otherwise untouched.
    msk = datetime(2030, 5, 9, 12, 0, tzinfo=timezone(timedelta(hours=3)))
    out = _coerce_validity_window(msk, end_of_day=True)
    assert out == datetime(2030, 5, 9, 9, 0, tzinfo=timezone.utc)

    # Naive midnight + end_of_day=True -> 23:59:59.999999 in app TZ.
    naive_mid = datetime(2030, 5, 9, 0, 0, 0)
    eod = _coerce_validity_window(naive_mid, end_of_day=True)
    assert eod is not None and eod.tzinfo is timezone.utc
    # 23:59:59.999999 Moscow == 20:59:59.999999 UTC.
    assert (eod.hour, eod.minute, eod.second) == (20, 59, 59)

    # Naive midnight + end_of_day=False -> 00:00:00 in app TZ.
    sod = _coerce_validity_window(naive_mid, end_of_day=False)
    assert sod is not None and sod.tzinfo is timezone.utc
    # 00:00 Moscow == 21:00 UTC the previous day.
    assert sod.day == 8 and sod.hour == 21 and sod.minute == 0

    # Non-midnight naive datetime: must be interpreted as Moscow local time
    # (NOT snapped to end-of-day) regardless of the end_of_day flag — the
    # admin explicitly typed the time, we trust it.
    naive_msk = datetime(2030, 5, 9, 15, 30, 0)
    out_eod = _coerce_validity_window(naive_msk, end_of_day=True)
    assert out_eod is not None and out_eod.tzinfo is timezone.utc
    # 15:30 MSK == 12:30 UTC same day.
    assert out_eod.year == 2030 and out_eod.month == 5 and out_eod.day == 9
    assert (out_eod.hour, out_eod.minute, out_eod.second) == (12, 30, 0)

    out_sod = _coerce_validity_window(naive_msk, end_of_day=False)
    assert out_sod == out_eod  # flag is ignored for non-midnight naive input


# ---------------------------------------------------------------------------
# Minute-precision valid_until via datetime-local input
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_promo_with_minute_precision_valid_until(  # noqa: ANN001
    client, admin_headers
):
    """The admin UI now uses ``<input type="datetime-local">`` which sends
    ``YYYY-MM-DDTHH:MM`` (naive). It must be interpreted as Moscow local
    time and stored in UTC. 15:30 MSK == 12:30 UTC.
    """
    r = await client.post(
        "/api/admin/promos",
        json={
            "type": "balance",
            "value": 500,
            "max_per_user": 1,
            "valid_until": "2030-05-09T15:30",
        },
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    parsed = datetime.fromisoformat(r.json()["valid_until"])
    assert parsed.tzinfo is not None
    in_utc = parsed.astimezone(timezone.utc)
    assert in_utc.year == 2030 and in_utc.month == 5 and in_utc.day == 9
    assert (in_utc.hour, in_utc.minute) == (12, 30)


@pytest.mark.asyncio
async def test_patch_promo_with_minute_precision_valid_until(  # noqa: ANN001
    client, admin_headers
):
    """PATCH must apply the same Moscow→UTC conversion for non-midnight
    naive datetimes — admins use the same datetime-local input on edit.
    """
    rc = await client.post(
        "/api/admin/promos",
        json={"type": "balance", "value": 500, "max_per_user": 1},
        headers=admin_headers,
    )
    assert rc.status_code == 201, rc.text
    pid = rc.json()["id"]

    rp = await client.patch(
        f"/api/admin/promos/{pid}",
        json={"valid_until": "2030-05-09T15:30"},
        headers=admin_headers,
    )
    assert rp.status_code == 200, rp.text
    parsed = datetime.fromisoformat(rp.json()["valid_until"])
    in_utc = parsed.astimezone(timezone.utc)
    assert in_utc.year == 2030 and in_utc.month == 5 and in_utc.day == 9
    assert (in_utc.hour, in_utc.minute) == (12, 30)
