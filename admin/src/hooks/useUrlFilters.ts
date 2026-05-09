import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';

/**
 * Type-safe wrapper over react-router's ``useSearchParams``.
 *
 * The store of truth is the URL — every filter change reflects into the
 * query-string so a) admins can deep-link to filtered views and b) the
 * Back button does the right thing. Defaults are *not* serialised, which
 * keeps URLs short and lets the backend treat "missing" as "use default".
 *
 * Usage:
 *   const { filters, setFilters, setFilter, reset } = useUrlFilters({
 *     defaults: { page: 1, status: '' },
 *     parsers: { page: (v) => Number(v) || 1 },
 *   });
 *
 * Values that match the default are *removed* from the URL on write. Reading
 * a missing key falls back to the default so call-sites can treat ``filters``
 * as a fully-populated record.
 */
export type FilterValue = string | number | boolean | undefined;
export type FilterRecord = Record<string, FilterValue>;

export interface UseUrlFiltersOptions<T extends FilterRecord> {
  defaults: T;
  /**
   * Per-key parsers convert the raw URL string into the typed value. Without
   * a parser, the value is passed through as a string (or ``undefined``).
   */
  parsers?: Partial<{ [K in keyof T]: (raw: string) => T[K] }>;
}

export interface UseUrlFiltersResult<T extends FilterRecord> {
  filters: T;
  setFilters: (patch: Partial<T>, opts?: { resetPage?: boolean }) => void;
  setFilter: <K extends keyof T>(key: K, value: T[K], opts?: { resetPage?: boolean }) => void;
  reset: () => void;
}

function serialise(value: FilterValue): string | null {
  if (value == null) return null;
  if (typeof value === 'boolean') return value ? '1' : null;
  const s = String(value);
  return s.length > 0 ? s : null;
}

export function useUrlFilters<T extends FilterRecord>(
  options: UseUrlFiltersOptions<T>
): UseUrlFiltersResult<T> {
  const { defaults, parsers } = options;
  const [searchParams, setSearchParams] = useSearchParams();

  // Recompute the typed view whenever the URL changes. This is cheap (small
  // keyspace) and keeps consumers from racing with stale snapshots.
  const filters = useMemo<T>(() => {
    const out = { ...defaults } as Record<string, FilterValue>;
    for (const key of Object.keys(defaults)) {
      const raw = searchParams.get(key);
      if (raw == null) continue;
      const parser = parsers?.[key as keyof T];
      if (parser) {
        out[key] = parser(raw);
      } else if (typeof defaults[key] === 'number') {
        const n = Number(raw);
        out[key] = Number.isFinite(n) ? n : defaults[key];
      } else if (typeof defaults[key] === 'boolean') {
        out[key] = raw === '1' || raw === 'true';
      } else {
        out[key] = raw;
      }
    }
    return out as T;
  }, [searchParams, defaults, parsers]);

  const setFilters = useCallback(
    (patch: Partial<T>, opts?: { resetPage?: boolean }) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          for (const [key, value] of Object.entries(patch)) {
            const def = defaults[key];
            const ser = serialise(value as FilterValue);
            // Strip the param when the new value matches its default — keeps
            // URLs minimal and avoids ?page=1&status=&q= noise.
            if (ser == null || ser === serialise(def as FilterValue)) {
              next.delete(key);
            } else {
              next.set(key, ser);
            }
          }
          if (opts?.resetPage && 'page' in defaults && !('page' in patch)) {
            next.delete('page');
          }
          return next;
        },
        { replace: true }
      );
    },
    [defaults, setSearchParams]
  );

  const setFilter = useCallback(
    <K extends keyof T>(key: K, value: T[K], opts?: { resetPage?: boolean }) => {
      setFilters({ [key]: value } as unknown as Partial<T>, opts);
    },
    [setFilters]
  );

  const reset = useCallback(() => {
    setSearchParams(new URLSearchParams(), { replace: true });
  }, [setSearchParams]);

  return { filters, setFilters, setFilter, reset };
}
