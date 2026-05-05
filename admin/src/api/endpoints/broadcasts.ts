import { apiClient } from '@/api/client';
import type {
  Broadcast,
  BroadcastCreatePayload,
  BroadcastRecipient,
  BroadcastSchedulePayload,
  BroadcastTestPayload,
  BroadcastUpdatePayload,
} from '@/types';

export interface BroadcastListParams {
  status?: string;
  limit?: number;
  offset?: number;
}

export async function listBroadcasts(params: BroadcastListParams = {}): Promise<Broadcast[]> {
  const { data } = await apiClient.get<Broadcast[]>('/admin/broadcasts', { params });
  return data;
}

export async function getBroadcast(id: number): Promise<Broadcast> {
  const { data } = await apiClient.get<Broadcast>(`/admin/broadcasts/${id}`);
  return data;
}

export async function createBroadcast(payload: BroadcastCreatePayload): Promise<Broadcast> {
  const { data } = await apiClient.post<Broadcast>('/admin/broadcasts', payload);
  return data;
}

export async function updateBroadcast(
  id: number,
  payload: BroadcastUpdatePayload
): Promise<Broadcast> {
  const { data } = await apiClient.patch<Broadcast>(`/admin/broadcasts/${id}`, payload);
  return data;
}

export async function uploadPhoto(id: number, file: File): Promise<Broadcast> {
  const form = new FormData();
  form.append('file', file);
  const { data } = await apiClient.post<Broadcast>(`/admin/broadcasts/${id}/photo`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data;
}

export async function sendBroadcast(id: number): Promise<Broadcast> {
  const { data } = await apiClient.post<Broadcast>(`/admin/broadcasts/${id}/send`);
  return data;
}

export async function scheduleBroadcast(
  id: number,
  payload: BroadcastSchedulePayload
): Promise<Broadcast> {
  const { data } = await apiClient.post<Broadcast>(
    `/admin/broadcasts/${id}/schedule`,
    payload
  );
  return data;
}

export async function cancelBroadcast(id: number): Promise<Broadcast> {
  const { data } = await apiClient.post<Broadcast>(`/admin/broadcasts/${id}/cancel`);
  return data;
}

export async function testBroadcast(
  id: number,
  payload: BroadcastTestPayload
): Promise<{ ok: boolean }> {
  const { data } = await apiClient.post<{ ok: boolean }>(
    `/admin/broadcasts/${id}/test`,
    payload
  );
  return data;
}

export async function getRecipients(id: number): Promise<BroadcastRecipient[]> {
  const { data } = await apiClient.get<BroadcastRecipient[]>(
    `/admin/broadcasts/${id}/recipients`
  );
  return data;
}
