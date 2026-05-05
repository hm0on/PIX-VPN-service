"""HTTP client for the Backend API (used by Stage 2+ tasks).

Stage 1: only the constructor — no calls are made yet. The instance is
created on worker startup and placed into `ctx["api_client"]`.
"""

from __future__ import annotations

import httpx

from app.config import Settings


def create_api_client(settings: Settings) -> httpx.AsyncClient:
    """Build an httpx.AsyncClient pre-configured for Backend API access."""
    headers = {
        "Authorization": f"Bearer {settings.backend_service_token.get_secret_value()}",
        "User-Agent": "vpn-pix-worker/0.1",
        "Accept": "application/json",
    }
    timeout = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)
    limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)

    return httpx.AsyncClient(
        base_url=settings.backend_api_url,
        headers=headers,
        timeout=timeout,
        limits=limits,
    )
