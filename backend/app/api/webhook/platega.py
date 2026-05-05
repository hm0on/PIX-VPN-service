"""Platega webhook endpoint."""

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


@router.post("/platega")
async def platega_webhook(
    request: Request,
    session: DBSession,
    northline: NorthLineClientDep,
    x_signature: str | None = Header(default=None, alias="X-Signature"),
) -> ORJSONResponse:
    body_bytes = await request.body()
    settings = get_settings()
    client = PlategaClient(
        api_key=settings.platega_api_key,
        shop_id=settings.platega_shop_id,
        secret=settings.platega_secret,
        base_url=settings.platega_api_url,
    )

    if not client.verify_webhook_signature(body_bytes, x_signature):
        await tech_log(
            session,
            action="webhook_platega_invalid_signature",
            payload={
                "body_preview": body_bytes[:512].decode("utf-8", errors="replace"),
                "signature_present": bool(x_signature),
            },
            trace_id=get_trace_id(),
        )
        await session.commit()
        raise ForbiddenError(
            "Invalid webhook signature", error_code="invalid_signature"
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

    # TODO: уточнить под реальное API Platega — имена полей в webhook payload.
    external_id = (
        payload.get("payment_id")
        or payload.get("invoice_id")
        or payload.get("id")
        or payload.get("orderId")
        or ""
    )
    status_value = str(payload.get("status") or "")
    if not external_id or not status_value:
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

    await tech_log(
        session,
        action="webhook_platega_received",
        payload={"external_id": external_id, "status": status_value},
        trace_id=get_trace_id(),
    )

    service = PaymentService(session)
    result = await service.process_webhook_payment(
        provider="platega",
        external_id=str(external_id),
        status_value=status_value,
        raw_meta=payload,
        trace_id=get_trace_id(),
        northline_client=northline,
    )
    await session.commit()
    return ORJSONResponse({"ok": True, "result": result})
