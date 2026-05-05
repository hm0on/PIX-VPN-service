"""FastAPI application entrypoint."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import redis.asyncio as redis_asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse

from app.api.admin import admin_router
from app.api.bot import bot_router
from app.api.health import router as public_health_router
from app.api.webhook import webhook_router
from app.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.db.session import dispose_engine, get_engine
from app.middleware import RequestLoggingMiddleware, TraceIDMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    logger = get_logger("startup")

    # Engine warmup (lazy creation but ensure it's reachable).
    engine = get_engine()
    app.state.engine = engine

    # Redis pool
    app.state.redis = redis_asyncio.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
    )

    logger.info("backend_started", env=settings.env, port=settings.backend_port)
    try:
        yield
    finally:
        logger.info("backend_shutting_down")
        try:
            await app.state.redis.aclose()
        except Exception as e:  # noqa: BLE001
            logger.warning("redis_close_failed", error=str(e))
        northline_client = getattr(app.state, "northline_client", None)
        if northline_client is not None:
            try:
                await northline_client.aclose()
            except Exception as e:  # noqa: BLE001
                logger.warning("northline_close_failed", error=str(e))
        await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="VPN_PIX Backend API",
        version="0.1.0",
        default_response_class=ORJSONResponse,
        lifespan=lifespan,
    )

    # CORS for admin SPA
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # Order matters: outermost first → trace id, then request logging.
    app.add_middleware(RequestLoggingMiddleware, service="backend")
    app.add_middleware(TraceIDMiddleware)

    register_exception_handlers(app)

    app.include_router(public_health_router)
    app.include_router(bot_router)
    app.include_router(admin_router)
    app.include_router(webhook_router)

    return app


app = create_app()
