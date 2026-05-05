"""Bot entrypoint — long polling.

Run with::

    python -m app.main

Order of middlewares (outer-first):
    1. TraceMiddleware            (assigns trace_id to the update)
    2. UserMiddleware             (upserts user via Backend, exposes db_user)
    3. BanMiddleware              (drops banned users silently)
    4. SubscriptionCheckMiddleware(forces channel subscription)
"""

from __future__ import annotations

import asyncio
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import ErrorEvent
from redis.asyncio import Redis

from app.api_client import BackendClient
from app.config import Settings, get_settings
from app.handlers import catalog as h_catalog
from app.handlers import getfileid as h_getfileid
from app.handlers import profile as h_profile
from app.handlers import purchase as h_purchase
from app.handlers import referral as h_referral
from app.handlers import start as h_start
from app.handlers import stubs as h_stubs
from app.handlers import support as h_support
from app.handlers import support_admin as h_support_admin
from app.handlers import topup as h_topup
from app.middlewares.ban import BanMiddleware
from app.middlewares.logging import TraceMiddleware
from app.middlewares.subscription_check import SubscriptionCheckMiddleware
from app.middlewares.user import UserMiddleware
from app.utils.errors import BackendUnavailableError
from app.utils.logging import (
    LOG_LEVEL_CRITICAL,
    bot_log,
    configure_logging,
    get_logger,
)
from app.utils.texts import TextService

log = get_logger("bot.main")


async def _on_error(event: ErrorEvent, **data: Any) -> bool:
    """Global aiogram error handler — log + friendly user reply.

    Aiogram passes whatever was in `data` for the offending update via kwargs.
    We try to recover ``texts``/``api`` from it for the user-facing reply and
    the backend log entry.
    """
    api: BackendClient | None = data.get("api")
    texts: TextService | None = data.get("texts")
    update = event.update
    exc = event.exception

    log.exception("dispatcher.unhandled_exception", error=str(exc))

    user_id: int | None = None
    if update.message and update.message.from_user:
        user_id = update.message.from_user.id
    elif update.callback_query and update.callback_query.from_user:
        user_id = update.callback_query.from_user.id

    await bot_log(
        api,
        level=LOG_LEVEL_CRITICAL,
        event="unhandled_exception",
        user_id=user_id,
        message=f"{type(exc).__name__}: {exc}",
        context={"update_id": update.update_id},
    )

    # Best-effort friendly reply.
    if texts is not None:
        try:
            text = await texts.get("unexpected_error")
            if update.message is not None:
                await update.message.answer(text)
            elif update.callback_query is not None and update.callback_query.message is not None:
                await update.callback_query.answer()
                await update.callback_query.message.answer(text)
        except Exception as nested:  # noqa: BLE001
            log.warning("dispatcher.error_reply_failed", error=str(nested))

    # Returning True tells aiogram the error is handled — no propagation.
    return True


async def _build_dispatcher(
    *,
    bot: Bot,
    settings: Settings,
    api: BackendClient,
    redis: Redis,
    texts: TextService,
) -> Dispatcher:
    """Create the Dispatcher, wire middlewares, register routers."""
    storage = RedisStorage(redis=redis)
    dp = Dispatcher(storage=storage)

    # Inject shared services into all handlers via DI.
    dp["api"] = api
    dp["redis"] = redis
    dp["texts"] = texts
    dp["settings"] = settings

    # Middleware order matters — outermost first.
    # `trace` is attached to the root update observer so EVERY update kind
    # gets a trace_id. The user/ban/sub middlewares operate on Message and
    # CallbackQuery — those observers deliver events as the inner type
    # (`Message` / `CallbackQuery`), which is what the middleware bodies
    # `isinstance`-check against.
    trace = TraceMiddleware()
    user_mw = UserMiddleware(api=api, texts=texts)
    ban = BanMiddleware()
    sub_check = SubscriptionCheckMiddleware(
        bot=bot, redis=redis, texts=texts, settings=settings
    )

    dp.update.outer_middleware(trace)
    for observer in (dp.message, dp.callback_query):
        observer.outer_middleware(user_mw)
        observer.outer_middleware(ban)
        observer.outer_middleware(sub_check)

    # Routers. Order matters when several routers register handlers for the
    # same callback prefix — first registered wins. Real Stage-2 handlers
    # are registered BEFORE stubs so the stub router only catches keys it
    # still owns ("support", "promo", "idea", "about").
    dp.include_router(h_start.router)
    dp.include_router(h_catalog.router)
    dp.include_router(h_purchase.router)
    dp.include_router(h_profile.router)
    dp.include_router(h_topup.router)
    dp.include_router(h_referral.router)
    # Stage 4 ticket routers. Admin-side comes FIRST so its support-group
    # filters intercept events before the user-side router (which assumes
    # private chats). Both must register before ``h_stubs``, which still
    # owns the legacy ``promo`` / ``about`` callbacks until later stages.
    # /getfileid lives in support group's General topic only — register
    # before support_admin so its narrower filter intercepts media first.
    dp.include_router(h_getfileid.router)
    dp.include_router(h_support_admin.router)
    dp.include_router(h_support.router)
    dp.include_router(h_stubs.router)

    # Global error handler.
    dp.errors.register(_on_error)

    return dp


async def _run() -> None:
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)

    log.info(
        "bot.starting",
        env=settings.ENV,
        backend=settings.BACKEND_API_URL,
        channel=settings.REQUIRED_CHANNEL_ID,
    )

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    api = BackendClient(settings)
    redis = Redis.from_url(settings.redis_url, decode_responses=False)
    texts = TextService(api, ttl_seconds=settings.TEXTS_CACHE_TTL_SECONDS)

    # Warm the texts cache once, but don't fail startup if backend isn't ready.
    try:
        await texts.get("main_menu")
    except BackendUnavailableError as exc:
        log.warning("bot.texts_warmup_failed", error=str(exc))

    dp = await _build_dispatcher(
        bot=bot, settings=settings, api=api, redis=redis, texts=texts
    )

    # ---- graceful shutdown ----
    async def _on_shutdown() -> None:
        log.info("bot.shutting_down")
        await api.aclose()
        await redis.aclose()
        log.info("bot.stopped")

    dp.shutdown.register(_on_shutdown)

    # `start_polling` installs SIGINT/SIGTERM handlers itself and returns
    # cleanly on signal — no manual signal plumbing needed here.
    try:
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
        )
    finally:
        await bot.session.close()


def main() -> None:
    """Sync entrypoint (so `python -m app.main` works)."""
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
