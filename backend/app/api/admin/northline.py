"""Admin → NorthLine reseller endpoints.

Thin proxy: every route forwards to :class:`NorthLineClient`, validates
the response with our admin-side Pydantic schemas, and audit-logs
mutating calls. We deliberately keep the router small — the heavy
lifting (retries, error mapping, JSON shape) is already in the client.

Routes
------
* ``GET  /admin/northline/profile``       — reseller balance/state.
* ``GET  /admin/northline/prices``        — partner price matrix.
* ``GET  /admin/northline/lte-packages``  — LTE catalogue.
* ``GET  /admin/northline/price-quote``   — proxied calculator.
* ``GET  /admin/northline/branding``      — current reseller-wide branding.
* ``PUT  /admin/northline/branding``      — patch branding (white-label).
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.core.exceptions import (
    NorthLineClientError,
    NorthLineUnavailableError,
)
from app.deps import AdminDep, DBSession, NorthLineClientDep
from app.schemas.admin_panel.northline import (
    AdminBrandingResponse,
    AdminBrandingUpdateRequest,
    AdminLtePackage,
    AdminLtePackagesResponse,
    AdminPriceMatrixRow,
    AdminPriceQuote,
    AdminResellerPrices,
    AdminResellerProfile,
)
from app.services.audit_service import record_admin_action

router = APIRouter()


def _wrap_provider_error(exc: Exception) -> Exception:
    """Re-raise provider errors as-is so the global handler maps them."""
    if isinstance(exc, NorthLineClientError | NorthLineUnavailableError):
        return exc
    # Unexpected — surface as a 502 via NorthLineUnavailableError so the
    # client sees a coherent error envelope instead of a 500 stacktrace.
    return NorthLineUnavailableError(
        "Unexpected error talking to NorthLine",
        details={"error": str(exc)},
    )


@router.get("/profile", response_model=AdminResellerProfile)
async def get_profile(
    _: AdminDep,
    northline: NorthLineClientDep,
) -> AdminResellerProfile:
    try:
        profile = await northline.get_profile()
    except Exception as exc:  # noqa: BLE001
        raise _wrap_provider_error(exc) from exc
    return AdminResellerProfile(
        provider_key=profile.provider_key,
        label=profile.label,
        balance_rub=profile.balance_rub,
        active=profile.active,
        issued_total=profile.issued_total,
        active_total=profile.active_total,
        spent_rub=profile.spent_rub,
    )


@router.get("/prices", response_model=AdminResellerPrices)
async def get_prices(
    _: AdminDep,
    northline: NorthLineClientDep,
) -> AdminResellerPrices:
    try:
        prices = await northline.get_prices()
    except Exception as exc:  # noqa: BLE001
        raise _wrap_provider_error(exc) from exc
    return AdminResellerPrices(
        provider_key=prices.provider_key,
        price_matrix=[
            AdminPriceMatrixRow(
                days=row.days,
                devices=row.devices,
                total_price_rub=row.total_price_rub,
                override_key=row.override_key,
            )
            for row in prices.price_matrix
        ],
    )


@router.get("/lte-packages", response_model=AdminLtePackagesResponse)
async def get_lte_packages(
    _: AdminDep,
    northline: NorthLineClientDep,
) -> AdminLtePackagesResponse:
    try:
        resp = await northline.get_lte_packages()
    except Exception as exc:  # noqa: BLE001
        raise _wrap_provider_error(exc) from exc
    return AdminLtePackagesResponse(
        packages=[
            AdminLtePackage(
                gb=p.gb,
                price_rub=p.price_rub,
                label=p.label,
                rate=p.rate,
            )
            for p in resp.packages
        ],
    )


@router.get("/price-quote", response_model=AdminPriceQuote)
async def get_price_quote(
    _: AdminDep,
    northline: NorthLineClientDep,
    days: int = Query(30, ge=1, le=3650),
    devices: int = Query(3, ge=1, le=64),
    unlimited: bool = Query(False),
    lte_gb: int = Query(0, ge=0, le=10_000),
) -> AdminPriceQuote:
    try:
        quote = await northline.price_quote(
            days=days,
            devices=devices,
            unlimited=unlimited,
            lte_gb=lte_gb,
        )
    except Exception as exc:  # noqa: BLE001
        raise _wrap_provider_error(exc) from exc
    return AdminPriceQuote.model_validate(quote.model_dump(mode="json"))


@router.get("/branding", response_model=AdminBrandingResponse)
async def get_branding(
    _: AdminDep,
    northline: NorthLineClientDep,
) -> AdminBrandingResponse:
    try:
        resp = await northline.get_branding()
    except Exception as exc:  # noqa: BLE001
        raise _wrap_provider_error(exc) from exc
    return AdminBrandingResponse(branding=resp.branding)


@router.put("/branding", response_model=AdminBrandingResponse)
async def set_branding(
    payload: AdminBrandingUpdateRequest,
    session: DBSession,
    admin: AdminDep,
    northline: NorthLineClientDep,
) -> AdminBrandingResponse:
    """Patch reseller-wide branding defaults.

    NorthLine validates ``custom_domain`` (DNS A-record must already
    resolve to their server IP) and rejects otherwise — we let that 4xx
    propagate to the admin UI as-is so the operator sees the real reason.
    """
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        # Empty payload — surface a 400 so the UI can show "nothing to
        # update" without us round-tripping to NorthLine for nothing.
        raise NorthLineClientError(
            error_code="empty_payload",
            error_message="Branding update requires at least one field",
            http_status=400,
        )
    try:
        await northline.set_branding(**fields)
        # Re-fetch so the response reflects the upstream's canonical view
        # (provider may normalise domains, lowercase, etc.).
        fresh = await northline.get_branding()
    except Exception as exc:  # noqa: BLE001
        raise _wrap_provider_error(exc) from exc

    await record_admin_action(
        session,
        admin,
        action="northline.branding.update",
        extra={"fields": sorted(fields.keys())},
    )
    await session.commit()
    return AdminBrandingResponse(branding=fresh.branding)
