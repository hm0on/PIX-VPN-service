"""Platega webhook endpoint.

Spec: https://docs.platega.io/

Авторизация callback'а — два заголовка X-MerchantId / X-Secret должны
совпадать с нашими credentials. Отдельной HMAC-подписи нет.

Payload:
    {
      "id": "<uuid>",
      "amount": <float>,
      "currency": "RUB",
      "status": "CONFIRMED" | "CANCELED" | "CHARGEBACKED",
      "paymentMethod": <int>,
      "payload": "<echo>"
    }

Отвечать 200 в течение 60 секунд, иначе Platega ретраит до 3-х раз
с интервалом 5 минут.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Header, Request
from fastapi.responses import ORJSONResponse

from app.config import get_settings
from app.core.exceptions import ForbiddenError
from app.core.logging import get_logger, get_trace_id, tech_log
from app.deps import DBSession, NorthLineClientDep
from app.services.payment_service import PaymentService
from app.services.platega_client import PlategaClient

logger = get_logger("webhook.platega")

router = APIRouter()


# Маппинг статусов Platega → внутренние ("paid"/"failed"/"expired"/"refunded"),
# которые понимает PaymentService.process_webhook_payment.
_STATUS_MAP: dict[str, str] = {
    "confirmed": "paid",
    "canceled": "failed",
    "cancelled": "failed",
    "chargebacked": "refunded",
    "pending": "pending",
}


@router.post("/platega")
async def platega_webhook(
    request: Request,
    session: DBSession,
    northline: NorthLineClientDep,
    x_merchant_id: str | None = Header(default=None, alias="X-MerchantId"),
    x_secret: str | None = Header(default=None, alias="X-Secret"),
) -> ORJSONResponse:
    body_bytes = await request.body()
    settings = get_settings()
    client = PlategaClient(
        api_key=settings.platega_api_key,
        shop_id=settings.platega_shop_id,
        secret=settings.platega_secret or settings.platega_api_key,
        base_url=settings.platega_api_url,
    )

    if not client.verify_webhook_credentials(x_merchant_id, x_secret):
        await tech_log(
            session,
            action="webhook_platega_invalid_credentials",
            payload={
                "body_preview": body_bytes[:512].decode("utf-8", errors="replace"),
                "merchant_id_present": bool(x_merchant_id),
                "secret_present": bool(x_secret),
            },
            trace_id=get_trace_id(),
        )
        await session.commit()
        raise ForbiddenError(
            "Invalid webhook credentials", error_code="invalid_signature"
        )

    try:
        payload: dict[str, Any] = json.loads(body_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        await tech_log(
            session,
            action="webhook_platega_bad_json",
            payload={"error": str(e)},
            trace_id=get_trace_id(),
        )
        await session.commit()
        return ORJSONResponse({"ok": False, "error": "invalid_json"}, status_code=400)

    external_id = str(payload.get("id") or "")
    raw_status = str(payload.get("status") or "")
    if not external_id or not raw_status:
        await tech_log(
            session,
            action="webhook_platega_missing_fields",
            payload={"received": payload},
            trace_id=get_trace_id(),
        )
        await session.commit()
        return ORJSONResponse(
            {"ok": False, "error": "missing_fields"}, status_code=400
        )

    # Маппим статусы Platega (UPPERCASE) → формат, который понимает PaymentService.
    normalized_status = _STATUS_MAP.get(raw_status.lower(), raw_status.lower())

    await tech_log(
        session,
        action="webhook_platega_received",
        payload={
            "external_id": external_id,
            "status_raw": raw_status,
            "status": normalized_status,
            "amount": payload.get("amount"),
        },
        trace_id=get_trace_id(),
    )

    service = PaymentService(session)
    result = await service.process_webhook_payment(
        provider="platega",
        external_id=external_id,
        status_value=normalized_status,
        raw_meta=payload,
        trace_id=get_trace_id(),
        northline_client=northline,
    )
    await session.commit()
    return ORJSONResponse({"ok": True, "result": result})
