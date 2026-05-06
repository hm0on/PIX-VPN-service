"""Stub callback handlers for sections not implemented yet.

Each stub answers with the `section_in_development` text and a "back to main
menu" button. As real handlers land they're peeled off this module:
catalog/profile/support/promo/idea/about all have dedicated routers now.

The router is kept around (and still mounted in ``app.main``) so we can
quickly attach a stub for any future menu entry without re-plumbing — just
add its callback to ``_STUB_CALLBACKS`` and bind a handler. With everything
implemented the set is intentionally empty and this router is a no-op.
"""

from __future__ import annotations

from aiogram import Router

from app.utils.logging import get_logger

router = Router(name="stubs")
log = get_logger("bot.handlers.stubs")


_STUB_CALLBACKS: frozenset[str] = frozenset()
