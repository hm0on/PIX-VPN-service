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
  page?: number;
  page_size?: number;
}

interface PromoListResponse {
  items: Promo[];
  total: number;
  page: number;
  page_size: number;
}

export async function listPromos(params: PromoListParams = {}): Promise<Promo[]> {
  // Backend returns AdminPromosPage{items, total, page, page_size}.
  // The page UI doesn't paginate yet, so we just unwrap items here and
  // keep the rest of the page (Promos.tsx) using a flat array.
  const { data } = await apiClient.get<PromoListResponse>('/admin/promos', {
    params: { page_size: 200, ...params },
  });
  return data.items ?? [];
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
