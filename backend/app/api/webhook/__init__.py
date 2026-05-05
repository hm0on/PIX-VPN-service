"""Public webhook routers (signature-verified, no service token guard)."""

from fastapi import APIRouter

from app.api.webhook import cryptobot, platega

webhook_router = APIRouter(prefix="/webhook", tags=["webhook"])
webhook_router.include_router(platega.router)
webhook_router.include_router(cryptobot.router)
