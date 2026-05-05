"""Admin-facing API routers."""

from fastapi import APIRouter, Depends

from app.api.admin import (
    auth,
    broadcasts,
    health,
    logs,
    promos,
    stats,
    subscriptions,
    tariffs,
    texts,
    users,
)
from app.deps import require_admin_jwt

admin_router = APIRouter(prefix="/api/admin", tags=["admin"])

# Auth router is mounted as-is; only POST /login is public — every other endpoint
# inside that router declares `AdminDep` per-route.
admin_router.include_router(auth.router, prefix="/auth")
admin_router.include_router(health.router)

# Stage 5 routers: protected by JWT at the router level.
admin_router.include_router(
    stats.router,
    prefix="/stats",
    dependencies=[Depends(require_admin_jwt)],
)
admin_router.include_router(
    users.router,
    prefix="/users",
    dependencies=[Depends(require_admin_jwt)],
)
admin_router.include_router(
    subscriptions.router,
    prefix="/subscriptions",
    dependencies=[Depends(require_admin_jwt)],
)

# Stage 5 PART 2 (this slice): tariffs / promos / broadcasts / texts / logs.
admin_router.include_router(
    tariffs.router,
    prefix="/tariffs",
    dependencies=[Depends(require_admin_jwt)],
)
admin_router.include_router(
    promos.router,
    prefix="/promos",
    dependencies=[Depends(require_admin_jwt)],
)
admin_router.include_router(
    broadcasts.router,
    prefix="/broadcasts",
    dependencies=[Depends(require_admin_jwt)],
)
admin_router.include_router(
    texts.router,
    prefix="/texts",
    dependencies=[Depends(require_admin_jwt)],
)
admin_router.include_router(
    logs.router,
    prefix="/logs",
    dependencies=[Depends(require_admin_jwt)],
)
