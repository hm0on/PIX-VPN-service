import { apiClient } from '@/api/client';
import type {
  Tariff,
  TariffCreatePayload,
  TariffDuration,
  TariffDurationPayload,
  TariffUpdatePayload,
} from '@/types';

export async function listTariffs(): Promise<Tariff[]> {
  const { data } = await apiClient.get<Tariff[]>('/admin/tariffs');
  return data;
}

export async function createTariff(payload: TariffCreatePayload): Promise<Tariff> {
  const { data } = await apiClient.post<Tariff>('/admin/tariffs', payload);
  return data;
}

export async function updateTariff(id: number, payload: TariffUpdatePayload): Promise<Tariff> {
  const { data } = await apiClient.patch<Tariff>(`/admin/tariffs/${id}`, payload);
  return data;
}

export async function removeTariff(id: number): Promise<void> {
  await apiClient.delete(`/admin/tariffs/${id}`);
}

export async function addDuration(
  tariffId: number,
  payload: TariffDurationPayload
): Promise<TariffDuration> {
  const { data } = await apiClient.post<TariffDuration>(
    `/admin/tariffs/${tariffId}/durations`,
    payload
  );
  return data;
}

export async function updateDuration(
  tariffId: number,
  durationId: number,
  payload: Partial<TariffDurationPayload>
): Promise<TariffDuration> {
  const { data } = await apiClient.patch<TariffDuration>(
    `/admin/tariffs/${tariffId}/durations/${durationId}`,
    payload
  );
  return data;
}

export async function removeDuration(tariffId: number, durationId: number): Promise<void> {
  await apiClient.delete(`/admin/tariffs/${tariffId}/durations/${durationId}`);
}
