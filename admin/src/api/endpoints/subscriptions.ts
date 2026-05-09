import { api } from '@/api/client';
import type {
  DeactivateRequest,
  Page,
  SubReconcileResponse,
  Subscription,
  SubscriptionBrandingRequest,
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
  /**
   * Per-subscription branding override. Pass ``null`` for a field to clear
   * it upstream (NorthLine PATCH /keys/{id}/branding semantics).
   */
  updateBranding: (id: number, payload: SubscriptionBrandingRequest) =>
    api.put<{ ok: true }, SubscriptionBrandingRequest>(
      `/admin/subscriptions/${id}/branding`,
      payload
    ),
  /**
   * Force-run the reconcile job on a single subscription. The response
   * describes what changed (status_flipped / expires_extended / no_change …)
   * so the UI can toast a meaningful summary.
   */
  reconcile: (id: number) =>
    api.post<SubReconcileResponse>(`/admin/subscriptions/${id}/reconcile`),
};
