"""Bot-facing API routers (auth via BACKEND_SERVICE_TOKEN)."""

from fastapi import APIRouter, Depends

from app.api.bot import (
    extension,
    free_trial,
    health,
    logs,
    outbox,
    profile,
    promo,
    purchase_balance,
    purchase_start,
    referral,
    subscriptions,
    support_topic,
    tariffs,
    texts,
    tickets,
    topup,
    users,
)
from app.deps import require_service_token

bot_router = APIRouter(
    prefix="/api/bot",
    tags=["bot"],
    dependencies=[Depends(require_service_token)],
)

bot_router.include_router(health.router)
bot_router.include_router(users.router)
bot_router.include_router(tickets.router)
bot_router.include_router(support_topic.router)
bot_router.include_router(texts.router)
bot_router.include_router(logs.router)
bot_router.include_router(purchase_start.router)
bot_router.include_router(topup.router)
bot_router.include_router(outbox.router)
bot_router.include_router(tariffs.router)
bot_router.include_router(free_trial.router)
bot_router.include_router(purchase_balance.router)
bot_router.include_router(profile.router)
bot_router.include_router(promo.router)
bot_router.include_router(referral.router)
bot_router.include_router(extension.router)
bot_router.include_router(subscriptions.router)
