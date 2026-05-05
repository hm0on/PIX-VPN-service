import { apiClient } from '@/api/client';
import { useAuthStore } from '@/stores/authStore';
import type { EventLog, EventLogsFilter, TechLog, TechLogsFilter } from '@/types';

interface EventsPage {
  items: EventLog[];
  next_before_id: number | null;
  total: number | null;
}

interface TechPage {
  items: TechLog[];
  next_before_id: number | null;
  total: number | null;
}

export async function listEvents(filter: EventLogsFilter = {}): Promise<EventLog[]> {
  const params: Record<string, unknown> = { ...filter };
  if (filter.level && filter.level.length > 0) {
    params.level = filter.level.join(',');
  } else {
    delete params.level;
  }
  // Backend returns AdminLogsPage{items, next_before_id, total}.
  const { data } = await apiClient.get<EventsPage>('/admin/logs/events', { params });
  return data.items ?? [];
}

/**
 * Open an EventSource against the live event stream. JWT is appended as a query
 * parameter because EventSource cannot send Authorization headers.
 */
export function eventsStream(): EventSource | null {
  const token = useAuthStore.getState().token;
  if (typeof window === 'undefined') return null;
  const baseURL = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? '/api';
  const url = new URL(`${baseURL}/admin/logs/events/stream`, window.location.origin);
  if (token) {
    url.searchParams.set('access_token', token);
  }
  return new EventSource(url.toString(), { withCredentials: false });
}

export async function listTech(filter: TechLogsFilter = {}): Promise<TechLog[]> {
  // Backend returns AdminTechLogsPage{items, next_before_id, total}.
  const { data } = await apiClient.get<TechPage>('/admin/logs/tech', { params: filter });
  return data.items ?? [];
}

export async function traceChain(traceId: string): Promise<TechLog[]> {
  const { data } = await apiClient.get<TechLog[]>(
    `/admin/logs/tech/trace/${encodeURIComponent(traceId)}`
  );
  return data;
}
