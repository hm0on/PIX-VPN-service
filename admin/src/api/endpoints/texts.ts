import { apiClient } from '@/api/client';
import type { BotText, BotTextUpdatePayload } from '@/types';

interface TextsListResponse {
  items: BotText[];
  total: number;
  page: number;
  page_size: number;
}

export async function listTexts(): Promise<BotText[]> {
  // Backend returns AdminTextsPage{items, total, page, page_size}.
  const { data } = await apiClient.get<TextsListResponse>('/admin/texts', {
    params: { page_size: 500 },
  });
  return data.items ?? [];
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
