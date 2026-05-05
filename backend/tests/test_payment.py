"""Payment endpoints + webhook tests."""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest
import pytest_asyncio

from app.config import get_settings
from app.schemas.platega import InvoiceResult


@pytest_asyncio.fixture
async def seeded_user(client, auth_headers):  # noqa: ANN001
    """Create a test user via the API."""
    payload = {"tg_id": 555001, "username": "payer"}
    r = await client.post("/api/bot/users", json=payload, headers=auth_headers)
    assert r.status_code == 200, r.text
    return r.json()["user"]


@pytest_asyncio.fixture
async def seeded_tariff(_engine_setup):  # noqa: ANN001
    """Insert a tariff + duration directly into the DB for the test."""
    from sqlalchemy import select

    from app.db.models.tariff import Tariff, TariffDuration
    from app.db.session import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        tariff = Tariff(
            code="basic_test",
            name="Basic Test",
            devices=3,
            sort_order=1,
            is_active=True,
            is_free_trial=False,
        )
        session.add(tariff)
        await session.flush()

        duration = TariffDuration(
            tariff_id=tariff.id,
            days=30,
            price_kopecks=18900,
            is_hot=False,
            is_active=True,
        )
        session.add(duration)
        await session.flush()
        await session.commit()

        # Re-read with IDs.
        tariff = (
            await session.execute(select(Tariff).where(Tariff.id == tariff.id))
        ).scalar_one()
        duration = (
            await session.execute(
                select(TariffDuration).where(TariffDuration.id == duration.id)
            )
        ).scalar_one()

        return {"tariff_id": tariff.id, "duration_id": duration.id}


@pytest.fixture
def patch_platega(monkeypatch):  # noqa: ANN001
    """Replace PlategaClient.create_invoice with an awaitable mock."""

    async def _fake_create_invoice(self, **kwargs):  # noqa: ANN001, ARG001
        order_id = kwargs["order_id"]
        return InvoiceResult(
            external_id=f"ext-{order_id}",
            payment_url=f"https://pay.example.test/{order_id}",
            raw={"mocked": True, "order_id": order_id},
        )

    from app.services import platega_client

    monkeypatch.setattr(
        platega_client.PlategaClient,
        "create_invoice",
        _fake_create_invoice,
    )
    yield


@pytest.fixture
def patch_cryptobot(monkeypatch):  # noqa: ANN001
    async def _fake_create_invoice(self, **kwargs):  # noqa: ANN001, ARG001
        order_id = kwargs["order_id"]
        return InvoiceResult(
            external_id=f"cb-{order_id}",
            payment_url=f"https://t.me/CryptoBot?start={order_id}",
            raw={"mocked": True},
        )

    from app.services import cryptobot_client

    monkeypatch.setattr(
        cryptobot_client.CryptoBotClient,
        "create_invoice",
        _fake_create_invoice,
    )
    yield


# ---------------------------------------------------------------------------
# /api/bot/purchase/start
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_purchase_start_sbp(
    client,  # noqa: ANN001
    auth_headers,
    seeded_user,
    seeded_tariff,
    patch_platega,
):
    body = {
        "tg_id": seeded_user["tg_id"],
        "tariff_id": seeded_tariff["tariff_id"],
        "duration_id": seeded_tariff["duration_id"],
        "provider": "platega_sbp",
    }
    r = await client.post("/api/bot/purchase/start", json=body, headers=auth_headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["payment_id"] > 0
    assert data["subscription_id"] > 0
    assert data["payment_url"].startswith("https://pay.example.test/")
    assert "expires_at" in data


@pytest.mark.asyncio
async def test_purchase_start_cryptobot(
    client,  # noqa: ANN001
    auth_headers,
    seeded_user,
    seeded_tariff,
    patch_cryptobot,
):
    body = {
        "tg_id": seeded_user["tg_id"],
        "tariff_id": seeded_tariff["tariff_id"],
        "duration_id": seeded_tariff["duration_id"],
        "provider": "cryptobot",
    }
    r = await client.post("/api/bot/purchase/start", json=body, headers=auth_headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["payment_url"].startswith("https://t.me/CryptoBot")


# ---------------------------------------------------------------------------
# /api/bot/topup/create
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_topup_min_amount_validation(
    client,  # noqa: ANN001
    auth_headers,
    seeded_user,
    patch_platega,
):
    body = {
        "tg_id": seeded_user["tg_id"],
        "amount_kopecks": 500,  # < 1000
        "provider": "platega_sbp",
    }
    r = await client.post("/api/bot/topup/create", json=body, headers=auth_headers)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "topup_amount_too_small"


@pytest.mark.asyncio
async def test_topup_create_ok(
    client,  # noqa: ANN001
    auth_headers,
    seeded_user,
    patch_platega,
):
    body = {
        "tg_id": seeded_user["tg_id"],
        "amount_kopecks": 50000,  # 500 RUB
        "provider": "platega_sbp",
    }
    r = await client.post("/api/bot/topup/create", json=body, headers=auth_headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["payment_id"] > 0
    assert data["payment_url"].startswith("https://pay.example.test/")


# ---------------------------------------------------------------------------
# Webhooks: signature, idempotency
# ---------------------------------------------------------------------------


def _platega_signature(secret: str, body_bytes: bytes) -> str:
    return hmac.new(secret.encode(), body_bytes, hashlib.sha256).hexdigest()


def _cryptobot_signature(token: str, body_bytes: bytes) -> str:
    secret = hashlib.sha256(token.encode()).digest()
    return hmac.new(secret, body_bytes, hashlib.sha256).hexdigest()


@pytest.mark.asyncio
async def test_platega_webhook_bad_signature(client):  # noqa: ANN001
    body = json.dumps({"orderId": "x", "status": "paid"}).encode()
    r = await client.post(
        "/webhook/platega",
        content=body,
        headers={"X-Signature": "deadbeef"},
    )
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "invalid_signature"


@pytest.mark.asyncio
async def test_cryptobot_webhook_bad_signature(client):  # noqa: ANN001
    body = json.dumps({"update_type": "invoice_paid"}).encode()
    r = await client.post(
        "/webhook/cryptobot",
        content=body,
        headers={"crypto-pay-api-signature": "deadbeef"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_platega_webhook_idempotent_topup(
    client,  # noqa: ANN001
    auth_headers,
    seeded_user,
    monkeypatch,
    patch_platega,
):
    # Configure secret so we can sign the webhook body.
    settings = get_settings()
    monkeypatch.setattr(settings, "platega_secret", "test_secret")  # noqa: S105
    monkeypatch.setattr(settings, "cryptobot_api_token", "test_token")  # noqa: S105

    # 1) Create a top-up payment.
    create_body = {
        "tg_id": seeded_user["tg_id"],
        "amount_kopecks": 30000,
        "provider": "platega_sbp",
    }
    r = await client.post(
        "/api/bot/topup/create", json=create_body, headers=auth_headers
    )
    assert r.status_code == 200, r.text
    payment_id = r.json()["payment_id"]
    external_id = f"ext-payment-{payment_id}"

    # 2) Send first webhook → marks paid + credits balance.
    webhook_body = json.dumps(
        {
            "id": external_id,
            "orderId": f"payment-{payment_id}",
            "status": "paid",
            "amount": 30000,
        }
    ).encode()
    sig = _platega_signature("test_secret", webhook_body)

    r1 = await client.post(
        "/webhook/platega",
        content=webhook_body,
        headers={"X-Signature": sig, "Content-Type": "application/json"},
    )
    assert r1.status_code == 200, r1.text

    # 3) Verify user balance increased.
    r_balance = await client.get(
        f"/api/bot/users/{seeded_user['tg_id']}", headers=auth_headers
    )
    assert r_balance.status_code == 200
    assert r_balance.json()["balance_kopecks"] == 30000

    # 4) Replay → must NOT double credit.
    r2 = await client.post(
        "/webhook/platega",
        content=webhook_body,
        headers={"X-Signature": sig, "Content-Type": "application/json"},
    )
    assert r2.status_code == 200
    assert r2.json()["result"]["ignored"] == "already_terminal"

    r_balance2 = await client.get(
        f"/api/bot/users/{seeded_user['tg_id']}", headers=auth_headers
    )
    assert r_balance2.json()["balance_kopecks"] == 30000  # still!


@pytest.mark.asyncio
async def test_platega_webhook_unknown_payment(client, monkeypatch):  # noqa: ANN001
    settings = get_settings()
    monkeypatch.setattr(settings, "platega_secret", "test_secret")  # noqa: S105

    body = json.dumps({"id": "nonexistent-99999", "status": "paid"}).encode()
    sig = _platega_signature("test_secret", body)
    r = await client.post(
        "/webhook/platega",
        content=body,
        headers={"X-Signature": sig, "Content-Type": "application/json"},
    )
    assert r.status_code == 200
    assert r.json()["result"]["ignored"] == "unknown_payment"


@pytest.mark.asyncio
async def test_cryptobot_webhook_signature_ok(
    client,  # noqa: ANN001
    monkeypatch,
):
    settings = get_settings()
    monkeypatch.setattr(settings, "cryptobot_api_token", "test_token")  # noqa: S105

    body = json.dumps(
        {
            "update_type": "invoice_paid",
            "payload": {"invoice_id": 999_888, "status": "paid"},
        }
    ).encode()
    sig = _cryptobot_signature("test_token", body)
    r = await client.post(
        "/webhook/cryptobot",
        content=body,
        headers={
            "crypto-pay-api-signature": sig,
            "Content-Type": "application/json",
        },
    )
    assert r.status_code == 200
    # Unknown payment → ignored without error.
    assert r.json()["result"]["ignored"] == "unknown_payment"
