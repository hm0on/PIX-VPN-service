import { apiClient } from '@/api/client';
import type { BotText, BotTextUpdatePayload } from '@/types';

export async function listTexts(): Promise<BotText[]> {
  const { data } = await apiClient.get<BotText[]>('/admin/texts');
  return data;
}

export async function getText(key: string): Promise<BotText> {
  const { data } = await apiClient.get<BotText>(`/admin/texts/${encodeURIComponent(key)}`);
  return data;
}

export async function updateText(
  key: string,
  payload: BotTextUpdatePayload
): Promise<BotText> {
  const { data } = await apiClient.patch<BotText>(
    `/admin/texts/${encodeURIComponent(key)}`,
    payload
  );
  return data;
}
