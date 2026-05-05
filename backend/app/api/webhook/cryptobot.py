"""CryptoBot webhook endpoint."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Header, Request
from fastapi.responses import ORJSONResponse

from app.config import get_settings
from app.core.exceptions import ForbiddenError
from app.core.logging import get_logger, get_trace_id, tech_log
from app.deps import DBSession, NorthLineClientDep
from app.services.cryptobot_client import CryptoBotClient
from app.services.payment_service import PaymentService

logger = get_logger("webhook.cryptobot")

router = APIRouter()


@router.post("/cryptobot")
async def cryptobot_webhook(
    request: Request,
    session: DBSession,
    northline: NorthLineClientDep,
    crypto_pay_api_signature: str | None = Header(
        default=None, alias="crypto-pay-api-signature"
    ),
) -> ORJSONResponse:
    body_bytes = await request.body()
    settings = get_settings()

    if not CryptoBotClient.verify_webhook_signature(
        body_bytes,
        crypto_pay_api_signature,
        settings.cryptobot_api_token,
    ):
        await tech_log(
            session,
            action="webhook_cryptobot_invalid_signature",
            payload={
                "body_preview": body_bytes[:512].decode("utf-8", errors="replace"),
                "signature_present": bool(crypto_pay_api_signature),
            },
            trace_id=get_trace_id(),
        )
        await session.commit()
        raise ForbiddenError(
            "Invalid webhook signature", error_code="invalid_signature"
        )

    try:
        update: dict[str, Any] = json.loads(body_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        await tech_log(
            session,
            action="webhook_cryptobot_bad_json",
            payload={"error": str(e)},
            trace_id=get_trace_id(),
        )
        await session.commit()
        return ORJSONResponse({"ok": False, "error": "invalid_json"}, status_code=400)

    update_type = str(update.get("update_type") or "")
    invoice_payload: dict[str, Any] = update.get("payload") or {}
    external_id = invoice_payload.get("invoice_id")
    raw_status = str(invoice_payload.get("status") or "")

    await tech_log(
        session,
        action="webhook_cryptobot_received",
        payload={
            "update_type": update_type,
            "external_id": external_id,
            "status": raw_status,
        },
        trace_id=get_trace_id(),
    )

    if update_type != "invoice_paid" or not external_id:
        # We only process paid events.
        await session.commit()
        return ORJSONResponse({"ok": True, "ignored": "non_paid_update"})

    service = PaymentService(session)
    result = await service.process_webhook_payment(
        provider="cryptobot",
        external_id=str(external_id),
        status_value="paid",
        raw_meta=update,
        trace_id=get_trace_id(),
        northline_client=northline,
    )
    await session.commit()
    return ORJSONResponse({"ok": True, "result": result})
