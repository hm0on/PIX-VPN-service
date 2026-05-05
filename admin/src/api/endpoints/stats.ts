import { api, apiClient } from '@/api/client';
import type {
  DashboardKPI,
  Period,
  RecentPayment,
  RecentUser,
  RevenuePoint,
  UsersPoint,
} from '@/types/api';
import { useAuthStore } from '@/stores/authStore';

export const statsApi = {
  dashboard: () => api.get<DashboardKPI>('/admin/stats/dashboard'),
  revenue: (period: Period) =>
    api.get<RevenuePoint[]>('/admin/stats/revenue', { period }),
  users: (period: Period) => api.get<UsersPoint[]>('/admin/stats/users', { period }),
  recentPayments: (limit = 10) =>
    api.get<RecentPayment[]>('/admin/stats/recent-payments', { limit }),
  recentUsers: (limit = 10) => api.get<RecentUser[]>('/admin/stats/recent-users', { limit }),
  /**
   * Open SSE stream for live KPI updates. Returns native EventSource.
   *
   * NOTE: EventSource cannot send custom headers, so the JWT is appended as
   * a query param. Backend must accept `?token=` for this endpoint.
   */
  openStream(): EventSource {
    const token = useAuthStore.getState().token ?? '';
    const base = apiClient.defaults.baseURL ?? '/api';
    const url = `${base.replace(/\/$/, '')}/admin/stats/stream?token=${encodeURIComponent(token)}`;
    return new EventSource(url, { withCredentials: false });
  },
};
