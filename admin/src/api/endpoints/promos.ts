import { apiClient } from '@/api/client';
import type {
  Promo,
  PromoActivation,
  PromoCreatePayload,
  PromoUpdatePayload,
} from '@/types';

export interface PromoListParams {
  is_active?: boolean;
  code?: string;
}

export async function listPromos(params: PromoListParams = {}): Promise<Promo[]> {
  const { data } = await apiClient.get<Promo[]>('/admin/promos', { params });
  return data;
}

export async function createPromo(payload: PromoCreatePayload): Promise<Promo> {
  const { data } = await apiClient.post<Promo>('/admin/promos', payload);
  return data;
}

export async function updatePromo(id: number, payload: PromoUpdatePayload): Promise<Promo> {
  const { data } = await apiClient.patch<Promo>(`/admin/promos/${id}`, payload);
  return data;
}

export async function getActivations(promoId: number): Promise<PromoActivation[]> {
  const { data } = await apiClient.get<PromoActivation[]>(
    `/admin/promos/${promoId}/activations`
  );
  return data;
}
