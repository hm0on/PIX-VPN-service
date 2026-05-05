import { api } from '@/api/client';
import type {
  DeactivateRequest,
  Page,
  Subscription,
  SubscriptionInfo,
  SubscriptionListParams,
} from '@/types/api';

export const subscriptionsApi = {
  list: (params: SubscriptionListParams) =>
    api.get<Page<Subscription>>('/admin/subscriptions', params as Record<string, unknown>),
  get: (id: number) => api.get<Subscription>(`/admin/subscriptions/${id}`),
  /**
   * Proxy to NorthLine.get_key. Backend may return 502 if upstream is down.
   */
  info: (id: number) => api.get<SubscriptionInfo>(`/admin/subscriptions/${id}/info`),
  deactivate: (id: number, payload: DeactivateRequest) =>
    api.post<Subscription, DeactivateRequest>(
      `/admin/subscriptions/${id}/deactivate`,
      payload
    ),
  removeDevice: (id: number, deviceId: string) =>
    api.delete<{ ok: boolean }>(`/admin/subscriptions/${id}/devices/${deviceId}`),
};
