/**
 * Runtime configuration sourced from Vite environment variables.
 * All values must be prefixed with `VITE_` to be exposed to the client bundle.
 */

const rawApiBase = import.meta.env.VITE_API_BASE_URL?.trim();

export const config = {
  /** Base URL for backend admin API. Defaults to relative `/api` (proxied by nginx). */
  apiBaseUrl: rawApiBase && rawApiBase.length > 0 ? rawApiBase : '/api',
  /** Polling interval for dashboard KPIs (ms). */
  dashboardPollMs: 60_000,
  /** TanStack Query default staleTime (ms). */
  defaultStaleTimeMs: 30_000,
} as const;

export type AppConfig = typeof config;
