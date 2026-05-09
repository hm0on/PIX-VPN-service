/**
 * NorthLine reseller admin DTOs.
 *
 * Mirrors backend.app.schemas.admin_panel.northline. Keep the field names in
 * sync with the Pydantic models — these are JSON-on-the-wire as-is.
 */

export interface NorthlineProfile {
  provider_key: string;
  label: string | null;
  balance_rub: number;
  active: boolean;
  issued_total: number;
  active_total: number;
  spent_rub: number;
}

export interface NorthlinePriceMatrixRow {
  days: number;
  devices: number;
  total_price_rub: number;
  override_key: string | null;
}

export interface NorthlinePrices {
  provider_key: string;
  price_matrix: NorthlinePriceMatrixRow[];
}

export interface NorthlineLtePackage {
  gb: number;
  price_rub: number;
  label: string | null;
  rate: number | null;
}

export interface NorthlineLtePackages {
  packages: NorthlineLtePackage[];
}

export interface NorthlinePriceQuoteParams {
  days: number;
  devices: number;
  unlimited?: boolean;
  lte_gb?: number;
}

export interface NorthlinePriceQuote {
  days: number;
  devices: number;
  tariff_code: string | null;
  total_price_rub: number;
  regular_price_rub: number | null;
  savings_rub: number | null;
  discount_pct: number | null;
  device_discount_pct: number | null;
  term_discount_pct: number | null;
  price_per_device_per_day: number | null;
  traffic_quota_gb: number | null;
  unlimited_traffic: boolean;
  lte_gb: number | null;
  lte_addon_rub: number | null;
  lte_rate_per_gb: number | null;
}

/**
 * NorthLine returns an open-ended dict of branding keys; we type the four
 * we render in the UI but keep the rest reachable for the JSON-debug view.
 */
export interface NorthlineBranding {
  custom_domain?: string | null;
  service_name?: string | null;
  service_description?: string | null;
  support_url?: string | null;
  [key: string]: unknown;
}

export interface NorthlineBrandingResponse {
  branding: NorthlineBranding;
}

export interface NorthlineBrandingUpdateRequest {
  custom_domain?: string | null;
  service_name?: string | null;
  service_description?: string | null;
  support_url?: string | null;
}
