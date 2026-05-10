import { api } from '@/api/client';
import type {
  DeactivateRequest,
  DeactivateResponse,
  Page,
  ResumeResponse,
  StopRequest,
  StopResponse,
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
  /**
   * Necrotic deactivation: вызывает NorthLine ``POST /keys/{id}/delete``,
   * провайдер сразу снимает ключ, в ответе приходит ``refund_rub`` (остаток).
   * После — БД-статус подписки уходит в ``deactivated`` (терминальный).
   */
  deactivate: (id: number, payload: DeactivateRequest) =>
    api.post<DeactivateResponse, DeactivateRequest>(
      `/admin/subscriptions/${id}/deactivate`,
      payload
    ),
  /**
   * Reversible pause: NorthLine ``POST /keys/{id}/stop``. Подписка переходит
   * в ``suspended`` — юзер не может подключиться, но ``expires_at`` тикает.
   */
  stop: (id: number, payload: StopRequest) =>
    api.post<StopResponse, StopRequest>(
      `/admin/subscriptions/${id}/stop`,
      payload
    ),
  /**
   * Снимает паузу: NorthLine ``POST /keys/{id}/resume``. Возвращает подписку
   * в ``active``. Доступно только из статуса ``suspended``.
   */
  resume: (id: number) =>
    api.post<ResumeResponse>(`/admin/subscriptions/${id}/resume`),
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
