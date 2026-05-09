"""One-shot: apply PIX VPN branding to the NorthLine reseller account.

Run inside the backend container::

    docker compose exec backend python -m scripts.apply_branding

The script is idempotent — NorthLine returns the merged result so you
can rerun it safely. ``custom_domain`` must already resolve (DNS A) to
the provider's server, which the operator confirmed is the case for
``sub.pix-app.xyz``.

Values are duplicated in the admin UI (PUT /admin/northline/branding)
so future tweaks don't require shell access; this script exists so the
first deploy doesn't depend on a shipped frontend.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

from app.config import get_settings
from app.services.northline_client import NorthLineClient


# Product-decided defaults. The support_url points at the bot itself
# rather than the support supergroup so end-users land in a private DM
# instead of a public chat.
BRANDING: dict[str, Any] = {
    "custom_domain": "sub.pix-app.xyz",
    "service_name": "PIX VPN",
    "service_description": (
        "Быстрый VPN с поддержкой LTE — pix-app.xyz"
    ),
    "support_url": "https://t.me/pix_vpn_robot",
}


async def main() -> int:
    settings = get_settings()
    if not (settings.northline_api_url and settings.northline_bearer_token):
        print(
            "[ERROR] NORTHLINE_API_URL / NORTHLINE_BEARER_TOKEN are not "
            "configured in .env",
            file=sys.stderr,
        )
        return 2

    client = NorthLineClient(
        base_url=settings.northline_api_url,
        bearer_token=settings.northline_bearer_token or "",
        provider_key=settings.northline_provider_key or "",
        test_mode=False,
    )

    print(f"Applying branding to {settings.northline_api_url}:")
    print(json.dumps(BRANDING, indent=2, ensure_ascii=False))
    try:
        await client.set_branding(**BRANDING)
        fresh = await client.get_branding()
    except Exception as exc:  # noqa: BLE001
        print(f"[FAILED] {exc!r}", file=sys.stderr)
        return 1

    print("\nNew reseller branding (provider's canonical view):")
    print(json.dumps(fresh.branding, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
